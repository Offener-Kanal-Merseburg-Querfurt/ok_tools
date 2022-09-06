from .import_legacy import IdNumberMap


def test__scripts__import_legacy__IdNumberMap__1(db):
    """Get id or number from an IdNumberMap."""
    map = IdNumberMap()
    map.add(1, 1)
    map.add(2, 1)
    map.add(3, 1)
    map.add(4, 2)
    map.add(5, 3)

    assert map.get_id(2) == 1
    assert map.get_numbers(1) == set((1, 2, 3))


def test__scripts__import_legacy__IdNumberMap__2(db):
    """Remove all numbers associated to an id."""
    map = IdNumberMap()
    map.add(1, 1)
    map.add(2, 1)
    map.add(3, 1)
    map.add(4, 2)
    map.add(5, 3)
    assert map.remove_by_id(1) == set((1, 2, 3))


def test__scripts__import_legacy__idNumberMap__3(db):
    """Add a id number tuple multiple times."""
    map = IdNumberMap()
    map.add(1, 3)
    map.add(1, 3)
    assert map.get_numbers(3) == set({1})
    assert map.get_id(1) == 3
