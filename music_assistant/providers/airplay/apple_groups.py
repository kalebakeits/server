"""
Read the Apple groups AirPlay devices advertise in their TXT records.

The Home app groups AirPlay devices into stereo pairs and Apple TV home theater
groups, and every device advertises that grouping in its AirPlay TXT record (see the
constants). Apple's own senders read it from discovery alone. This module only parses
it: what discovery shows is turned into the groups and their members, in the order
they lead, without any state of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .constants import APPLE_GROUP_HOME_THEATER, APPLE_GROUP_STEREO_PAIR
from .helpers import get_decoded_property

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .player import AirPlayPlayer

# a group's leader (the Apple TV) sorts after its speakers: the speakers carry the audio
_LEADER_POSITION = 1000


@dataclass(frozen=True)
class AppleGroupMembership:
    """The Apple group a device advertises it belongs to."""

    group_id: str
    group_type: str
    name: str | None
    # where the member goes in the group's member list (leader preference order)
    position: int


@dataclass
class AppleGroup:
    """An Apple group as discovery currently shows it."""

    group_id: str
    group_type: str
    name: str | None = None
    # (position, protocol id) of each member discovery shows
    members: list[tuple[int, str]] = field(default_factory=list)
    # the member advertising itself as the group's leader (igl): the Apple TV
    leader_id: str | None = None

    @property
    def member_ids(self) -> list[str]:
        """Return the member protocol ids, the speakers in their order, the leader last."""
        return [protocol_id for _, protocol_id in sorted(self.members)]

    @property
    def speaker_ids(self) -> list[str]:
        """Return the protocol ids of the members that carry the audio, in their order."""
        return [x for x in self.member_ids if x != self.leader_id]


def get_home_theater_membership(player: AirPlayPlayer) -> AppleGroupMembership | None:
    """
    Return the Apple TV home theater group a device advertises, if any.

    :param player: The AirPlay player to read the discovery info of.
    """
    if (info := player.airplay_discovery_info) is None:
        return None
    if not (psgid := get_decoded_property(info, "psgid")):
        return None
    if get_decoded_property(info, "psgtp") is None:
        return None
    pgid = get_decoded_property(info, "pgid")
    if pgid is None and get_decoded_property(info, "igl") == "1":
        # the group's leader (the Apple TV) advertises the group without pgid
        position = _LEADER_POSITION
    elif pgid is not None and pgid.upper() == psgid.upper():
        try:
            position = int(get_decoded_property(info, "pgmid") or 0)
        except ValueError:
            position = 0
    else:
        return None
    return AppleGroupMembership(
        group_id=psgid.upper(),
        group_type=APPLE_GROUP_HOME_THEATER,
        name=get_decoded_property(info, "gpn"),
        position=position,
    )


def get_stereo_pair_membership(player: AirPlayPlayer) -> AppleGroupMembership | None:
    """
    Return the stereo pair a device advertises, if any.

    :param player: The AirPlay player to read the discovery info of.
    """
    if (info := player.airplay_discovery_info) is None:
        return None
    if not (tsid := get_decoded_property(info, "tsid")):
        return None
    # gid is "<tsid>+<role>+<device id>" within a pair: order the pair by role
    position = 0
    gid_parts = (get_decoded_property(info, "gid") or "").split("+")
    if len(gid_parts) == 3 and gid_parts[1].isdigit():
        position = int(gid_parts[1])
    return AppleGroupMembership(
        group_id=tsid.upper(),
        group_type=APPLE_GROUP_STEREO_PAIR,
        name=get_decoded_property(info, "gpn"),
        position=position,
    )


def find_apple_groups(players: Iterable[AirPlayPlayer]) -> dict[str, AppleGroup]:
    """
    Return the Apple groups the given players advertise, keyed on group id.

    A stereo pair inside an Apple TV home theater group plays as part of that group,
    as an iPhone shows it, so it only forms a group of its own when it is not in one.
    A group discovery shows only one member of is returned too: its other members
    may not have been discovered yet.

    :param players: The AirPlay players discovery currently shows.
    """
    present = [p for p in players if p.airplay_discovery_info is not None]
    found: dict[str, AppleGroup] = {}
    in_home_theater: set[str] = set()
    for group_type, get_membership in (
        (APPLE_GROUP_HOME_THEATER, get_home_theater_membership),
        (APPLE_GROUP_STEREO_PAIR, get_stereo_pair_membership),
    ):
        for player in present:
            if player.protocol_id in in_home_theater:
                continue
            if (membership := get_membership(player)) is None:
                continue
            group = found.setdefault(
                membership.group_id, AppleGroup(membership.group_id, group_type)
            )
            group.name = group.name or membership.name
            group.members.append((membership.position, player.protocol_id))
            if membership.position == _LEADER_POSITION:
                group.leader_id = player.protocol_id
        if group_type == APPLE_GROUP_HOME_THEATER:
            in_home_theater = {
                protocol_id
                for group in found.values()
                if len(group.members) > 1
                for _, protocol_id in group.members
            }
    return found
