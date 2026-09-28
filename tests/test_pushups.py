from pushups import calculate_pushups, get_player_category

AVG = {"Kbar": 10, "Abar": 20, "Dbar": 10}


def test_category_ignores_key_order():
    # STD est déclaré en premier dans players.json de test.
    assert get_player_category("A")[0] == "ELT"


def test_unknown_player_is_std():
    assert get_player_category("Inconnu")[0] == "STD"


def test_average_game_gives_base():
    # Partie parfaitement dans la moyenne, victoire, sans bonus : BASE.
    assert calculate_pushups(10, 10, 20, "Z", AVG, win=True) == (15, "STD")


def test_loss_adds_three():
    assert calculate_pushups(10, 10, 20, "Z", AVG, win=False)[0] == 18


def test_bonuses_and_maluses():
    assert calculate_pushups(10, 10, 20, "Z", AVG, win=True, fb_victim=True)[0] == 16
    assert calculate_pushups(10, 10, 20, "Z", AVG, win=True, fb_kill=True, top_damage=True)[0] == 13


def test_more_deaths_more_pushups():
    # Deux fois plus de morts que la moyenne : + MULT_MORT (12).
    assert calculate_pushups(10, 20, 20, "Z", AVG, win=True)[0] == 27


def test_floor_at_min_pompes():
    # Partie énorme : le total est planché au minimum de la catégorie.
    assert calculate_pushups(60, 0, 60, "Z", AVG, win=True)[0] == 5
    assert calculate_pushups(60, 0, 60, "A", AVG, win=True) == (15, "ELT")


def test_zero_average_deaths_does_not_crash():
    assert calculate_pushups(5, 3, 5, "Z", {"Kbar": 0, "Abar": 0, "Dbar": 0}, win=True)[0] >= 5
