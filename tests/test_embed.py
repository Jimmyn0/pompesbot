from embed_builder import build_embed, mark_player_done


def _result(name, pompes, k=1, d=1, a=1, win=True, icons=""):
    return {"name": name, "champ": "<:Jinx:1>", "kills": k, "deaths": d, "assists": a, "damage": 12345,
            "win": win, "pompes": pompes, "icons": icons}


def test_three_aligned_columns():
    embed = build_embed([_result("A", 15), _result("B", 45, d=9, icons="💀")], "EUW1_1", "ARAM")
    joueur, stats, pompes = embed.fields[:3]
    assert (joueur.name, stats.name, pompes.name) == ("Joueur", "KDA · Dmg", "💪 Pompes")
    assert all(f.inline for f in embed.fields[:3])
    assert len(joueur.value.splitlines()) == len(stats.value.splitlines()) == len(pompes.value.splitlines()) == 2
    assert "```" not in joueur.value                  # pas de bloc de code : les icônes s'affichent
    assert joueur.value.splitlines()[0] == "<:Jinx:1> **A** ★"
    assert stats.value.splitlines()[1] == "`1/9/1` · 12k"
    assert pompes.value.splitlines()[1] == "**45** 💀"


def test_title_and_color_follow_result():
    win = build_embed([_result("A", 15)], "EUW1_1", "Arena")
    loss = build_embed([_result("A", 15, win=False)], "EUW1_1", "URF")
    assert win.title == "Fin de partie Arena — 🏆 VICTOIRE"
    assert loss.title == "Fin de partie URF — 💀 DÉFAITE"
    assert win.color != loss.color


def test_legend_has_no_blood_drops():
    legend = build_embed([_result("A", 15), _result("B", 20)], "EUW1_1").fields[3].value
    assert "🩸" not in legend and "🗡️ First Blood" in legend and "💀 First Death" in legend


def test_mark_player_done():
    embed = build_embed([_result("A", 15), _result("B", 45)], "EUW1_1")
    marked = mark_player_done(embed, "B")
    assert marked.fields[2].value.splitlines() == ["**15**", "**45** ✅"]
    assert mark_player_done(marked, "B").fields[2].value == marked.fields[2].value   # idempotent
    assert embed.fields[2].value.splitlines() == ["**15**", "**45**"]                # original inchangé


def test_achievements_and_records_sections():
    embed = build_embed([_result("A", 15, d=0, icons="🛡️")], "EUW1_1",
                        achievements=[("A", "intouchable")], records=["⚔️ **A** — record de kills : 30 kills"])
    fields = {f.name: f.value for f in embed.fields}
    assert fields["🏅 Succès débloqués"] == "**A** — 🛡️ Intouchable"
    assert fields["📈 Records de la saison"].startswith("⚔️ **A**")
    legend = embed.fields[-1].value
    assert "🛡️ Sans mort −5" in legend and "Série noire" not in legend
    assert "Clique sur un joueur" in legend
