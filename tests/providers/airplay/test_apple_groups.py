"""Tests for reading the Apple groups AirPlay devices advertise."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from music_assistant.providers.airplay.apple_groups import (
    find_apple_groups,
    get_home_theater_membership,
    get_stereo_pair_membership,
)
from music_assistant.providers.airplay.constants import (
    APPLE_GROUP_HOME_THEATER,
    APPLE_GROUP_STEREO_PAIR,
)

# TXT records as an Apple TV and a HomePod stereo pair advertise them (trimmed to the
# grouping fields), in the setups the Home app produces
HOME_THEATER_ID = "FBE1CA53-98F2-573F-872E-2805C5918EE7"
PAIR_ID = "C672647A-920D-51DE-9372-59D923569682"
APPLE_TV_LINKED = {
    "model": "AppleTV11,1",
    "gpn": "Living Room TV",
    "gid": HOME_THEATER_ID,
    "igl": "1",
    "gcgl": "1",
    "psgid": HOME_THEATER_ID,
    "psgtp": "1",
    "psgsz": "3",
    "pgm": "0",
    "pgmid": "0",
}
LEFT_LINKED = {
    "model": "AudioAccessory1,1",
    "gpn": "Living Room TV",
    "gid": HOME_THEATER_ID,
    "igl": "0",
    "gcgl": "1",
    "psgid": HOME_THEATER_ID,
    "psgtp": "1",
    "psgsz": "3",
    "pgid": HOME_THEATER_ID,
    "pgm": "0",
    "pgmid": "2",
    "tsid": "45886F4D-F128-569C-865B-2617893EEBF7",
}
RIGHT_LINKED = {**LEFT_LINKED, "pgmid": "1"}
LEFT_PAIRED = {
    "model": "AudioAccessory1,1",
    "gpn": "Bedroom",
    "gid": f"{PAIR_ID}+1+936C22C6-C719-484C-8427-60352257117E",
    "igl": "1",
    "gcgl": "1",
    "tsid": PAIR_ID,
}
RIGHT_PAIRED = {
    **LEFT_PAIRED,
    "gid": f"{PAIR_ID}+0+2A324828-C582-49FE-BCD6-D5DB9F6231E8",
}
APPLE_TV_ALONE = {
    "model": "AppleTV11,1",
    "gid": "04F9B7A2-135B-4394-A409-52EA4DB2FC1D",
    "igl": "1",
    "gcgl": "1",
}
SPEAKER_ALONE = {
    "model": "AudioAccessory1,1",
    "gid": "F36CEB65-A90F-4BFA-8963-171C7A76A4F8+936C22C6-C719-484C-8427-60352257117E",
    "igl": "1",
    "gcgl": "1",
}


def _player(protocol_id: str, properties: dict[str, str] | None) -> MagicMock:
    """
    Create a mock AirPlay player advertising the given TXT record.

    :param protocol_id: The protocol id.
    :param properties: The decoded TXT record, or None for no AirPlay discovery info.
    """
    player = MagicMock()
    player.protocol_id = protocol_id
    player.airplay_discovery_info = (
        None if properties is None else SimpleNamespace(decoded_properties=properties)
    )
    return player


def test_home_theater_membership_marks_the_apple_tv_as_leader() -> None:
    """The Apple TV leads its home theater group; its speakers hold their slots."""
    apple_tv = get_home_theater_membership(_player("apple_tv", APPLE_TV_LINKED))
    right = get_home_theater_membership(_player("right", RIGHT_LINKED))
    assert apple_tv is not None
    assert right is not None
    assert apple_tv.group_id == right.group_id == HOME_THEATER_ID
    assert apple_tv.group_type == APPLE_GROUP_HOME_THEATER
    assert apple_tv.name == "Living Room TV"
    assert right.position == 1
    assert apple_tv.position > right.position


def test_speaker_paired_into_another_group_is_no_home_theater_member() -> None:
    """A speaker whose pgid differs from its psgid is not a member of that group."""
    assert get_home_theater_membership(_player("x", {**LEFT_LINKED, "pgid": "OTHER"})) is None


def test_stereo_pair_membership_orders_by_role() -> None:
    """A stereo pair is keyed on tsid and ordered by the role inside gid."""
    left = get_stereo_pair_membership(_player("left", LEFT_PAIRED))
    right = get_stereo_pair_membership(_player("right", RIGHT_PAIRED))
    assert left is not None
    assert right is not None
    assert left.group_id == right.group_id == PAIR_ID
    assert left.group_type == APPLE_GROUP_STEREO_PAIR
    assert left.name == "Bedroom"
    assert (right.position, left.position) == (0, 1)


def test_standalone_devices_advertise_no_group() -> None:
    """Devices outside any Home app grouping belong to no Apple group."""
    for properties in (APPLE_TV_ALONE, SPEAKER_ALONE):
        assert get_home_theater_membership(_player("x", properties)) is None
        assert get_stereo_pair_membership(_player("x", properties)) is None


def test_keys_are_read_in_any_casing() -> None:
    """TXT keys are case-insensitive, and so is the group id."""
    properties = {k.upper(): v.lower() for k, v in LEFT_LINKED.items()}
    membership = get_home_theater_membership(_player("left", properties))
    assert membership is not None
    assert membership.group_id == HOME_THEATER_ID


def test_stereo_pair_inside_a_home_theater_group_plays_as_part_of_it() -> None:
    """A pair linked to an Apple TV forms one home theater group, the speakers first."""
    found = find_apple_groups(
        [
            _player("apple_tv", APPLE_TV_LINKED),
            _player("left", LEFT_LINKED),
            _player("right", RIGHT_LINKED),
        ]
    )
    assert list(found) == [HOME_THEATER_ID]
    group = found[HOME_THEATER_ID]
    assert group.group_type == APPLE_GROUP_HOME_THEATER
    assert group.member_ids == ["right", "left", "apple_tv"]
    assert group.speaker_ids == ["right", "left"]
    assert group.leader_id == "apple_tv"
    assert group.name == "Living Room TV"


def test_a_stereo_pair_on_its_own_is_found() -> None:
    """Both speakers of a pair form one group named after the pair, in role order."""
    found = find_apple_groups([_player("left", LEFT_PAIRED), _player("right", RIGHT_PAIRED)])
    assert list(found) == [PAIR_ID]
    group = found[PAIR_ID]
    assert group.group_type == APPLE_GROUP_STEREO_PAIR
    assert group.member_ids == ["right", "left"]
    assert group.leader_id is None
    assert group.name == "Bedroom"


def test_a_pair_whose_apple_tv_is_not_discovered_is_found_as_a_pair() -> None:
    """Until a second home theater member shows up, the pair stands on its own."""
    found = find_apple_groups([_player("left", LEFT_LINKED)])
    assert found[HOME_THEATER_ID].member_ids == ["left"]
    assert found[LEFT_LINKED["tsid"]].member_ids == ["left"]


def test_devices_without_a_group_or_discovery_info_are_left_out() -> None:
    """Standalone devices, and devices without AirPlay discovery info, form no group."""
    found = find_apple_groups(
        [
            _player("apple_tv", APPLE_TV_ALONE),
            _player("speaker", SPEAKER_ALONE),
            _player("raop_only", None),
        ]
    )
    assert found == {}
