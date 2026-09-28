import os
import random
import time

from fakes import FakeChannel

import config
import db
import dev
import loop

OWNER = ("pA", "A")
FRIENDS = [("pB", "B"), ("pC", "C")]


def test_dev_mode_never_on_production_data(tmp_path):
    base = str(tmp_path)
    assert config.dev_mode_enabled("1", str(tmp_path / "test"), base)
    assert not config.dev_mode_enabled("1", base, base)                  # données de production
    # Même dossier écrit avec une autre casse : refusé là où le système ignore la casse (Windows).
    same_on_this_os = os.path.normcase(base.upper()) == os.path.normcase(base)
    assert config.dev_mode_enabled("1", base.upper(), base) is not same_on_this_os
    assert not config.dev_mode_enabled(None, str(tmp_path / "test"), base)


def test_fake_aram_match():
    match_id, info, (killer, victim) = dev.fake_match([OWNER, *FRIENDS], "ARAM", win=False, rng=random.Random(1))
    parts = info["participants"]
    assert match_id.startswith("TEST_") and info["queueId"] == 450
    assert len(parts) == 10 and killer != victim
    ours = [p for p in parts if p["teamId"] == 100]
    assert [p["puuid"] for p in ours[:3]] == ["pA", "pB", "pC"] and len(ours) == 5
    assert all(not p["win"] for p in ours) and all(p["win"] for p in parts if p["teamId"] == 200)
    assert len({p["championId"] for p in parts}) == 10                  # champions distincts


def test_fake_arena_duos():
    _, info, _ = dev.fake_match([OWNER, *FRIENDS], "Arena", win=True, rng=random.Random(2))
    parts = info["participants"]
    assert info["gameMode"] == "CHERRY" and len(parts) == 16
    duo = {p["puuid"]: p["playerSubteamId"] for p in parts}
    assert duo["pA"] == duo["pB"] == 1 and duo["pC"] != 1
    assert all(p["win"] for p in parts if p["playerSubteamId"] == 1)


def test_owner_options():
    _, info, (killer, victim) = dev.fake_match([OWNER], "URF", win=True, owner_deathless=True,
                                               owner_pentakill=True, rng=random.Random(3))
    owner = info["participants"][0]
    assert owner["deaths"] == 0 and owner["pentaKills"] == 1 and owner["kills"] >= 12
    assert victim != 1                                                   # pas de first death sans mourir


async def test_fake_match_goes_through_the_real_pipeline(riot):
    db.record_team("EUW1_1", {"pB": "B"})
    db.record_team("EUW1_2", {"pB": "B"})                                 # B est un pote
    match_id, info, first_blood = dev.fake_match([OWNER, ("pB", "B")], "ARAM", win=True, owner_deathless=True,
                                                 rng=random.Random(4))
    channel = FakeChannel()
    assert await loop.post_match(channel, match_id, info, "ARAM", time.time(), "pA", first_blood)

    embed, view = channel.sent[0]
    names = [line.split("**")[1] for line in embed.fields[0].value.splitlines()]
    assert set(names) == {"A", "B"}                                        # les inconnus ne comptent pas
    assert [c.custom_id.split(":")[1] for c in view.children] == ["detail", "detail", "done"]
    assert db.has_achievement("pA", "intouchable")
    assert db.conn().execute("SELECT COUNT(*) FROM games WHERE match_id = ?", (match_id,)).fetchone()[0] == 2
    # Une fausse partie ne modifie pas la détection des potes.
    assert db.conn().execute("SELECT COUNT(*) FROM owner_teams WHERE match_id = ?", (match_id,)).fetchone()[0] == 0
