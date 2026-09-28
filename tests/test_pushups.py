from pushups import calculate_pushups, get_player_category

AVG = {"Kbar": 10, "Abar": 20, "Dbar": 10}


def pompes(*args, **kwargs) -> int:
    return calculate_pushups(*args, **kwargs)[0]


def test_category_ignores_key_order():
    # STD est déclaré en premier dans players.json de test.
    assert get_player_category("A")[0] == "ELT"


def test_unknown_player_is_std():
    assert get_player_category("Inconnu")[0] == "STD"


def test_average_game_gives_base():
    # Partie parfaitement dans la moyenne, victoire, sans bonus : BASE.
    assert calculate_pushups(10, 10, 20, "Z", AVG, win=True)[:2] == (15, "STD")


def test_loss_adds_three():
    assert pompes(10, 10, 20, "Z", AVG, win=False) == 18


def test_bonuses_and_maluses():
    assert pompes(10, 10, 20, "Z", AVG, win=True, fb_victim=True) == 16
    assert pompes(10, 10, 20, "Z", AVG, win=True, fb_kill=True, top_damage=True) == 13


def test_more_deaths_more_pushups():
    # Deux fois plus de morts que la moyenne : + MULT_MORT (12).
    assert pompes(10, 20, 20, "Z", AVG, win=True) == 27


def test_floor_at_min_pompes():
    # Partie énorme : le total est planché au minimum de la catégorie.
    assert pompes(60, 1, 60, "Z", AVG, win=True) == 5
    assert calculate_pushups(60, 1, 60, "A", AVG, win=True)[:2] == (15, "ELT")


def test_zero_average_deaths_does_not_crash():
    assert pompes(5, 3, 5, "Z", {"Kbar": 0, "Abar": 0, "Dbar": 0}, win=True) >= 5


def test_loss_streak_multiplier_from_third_loss():
    assert pompes(10, 10, 20, "Z", AVG, win=False, loss_streak=2) == 18
    assert pompes(10, 10, 20, "Z", AVG, win=False, loss_streak=3) == round(18 * 1.2)
    assert pompes(10, 10, 20, "Z", AVG, win=True, loss_streak=3) == 15   # ignoré sur une victoire


def test_deathless_bonus_can_go_below_min_but_not_zero():
    # 0 mort : 15 − 12 = 3, remonté au minimum de 5, puis −5 → 0.
    total, _, b = calculate_pushups(10, 0, 20, "Z", AVG, win=True)
    assert total == 0 and b["deathless"] and b["floored"]
    # Défaite sans mort pour A (ELT) : 30 − 18 + 9 + 3 = 24, puis −5.
    assert pompes(5, 0, 10, "A", AVG, win=False) == 19


def test_breakdown_explains_the_result():
    total, _, b = calculate_pushups(4, 7, 13, "A", AVG, win=False, fb_victim=True, top_damage=True)
    assert b["category"] == "ELT" and b["min"] == 15
    assert b["kda"] == [4, 7, 13] and b["avg"] == {"K": 10, "A": 20, "D": 10}
    assert [label for label, _ in b["steps"]] == ["Base", "Morts", "Kills et assists", "Défaite", "First death",
                                                   "Top dégâts"]
    assert round(sum(v for _, v in b["steps"]), 1) == b["raw"]
    assert b["final"] == total
