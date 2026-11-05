// Where each pitch slot sits on the tactics board (x, y in % of width/height; attack is upward).
import type { PlayerOut, Role } from "./api";

type XY = [number, number];
const BACK4: Record<string, XY> = { GK: [50, 90], LB: [14, 70], LCB: [37, 75], RCB: [63, 75], RB: [86, 70] };
const BACK3: Record<string, XY> = { GK: [50, 90], LCB: [26, 74], CB: [50, 76], RCB: [74, 74] };

export const SLOT_XY: Record<string, Record<string, XY>> = {
  "4-3-3": { ...BACK4, LCM: [27, 50], CM: [50, 54], RCM: [73, 50], LW: [18, 26], ST: [50, 19], RW: [82, 26] },
  "4-2-3-1": { ...BACK4, LDM: [37, 57], RDM: [63, 57], LAM: [19, 36], CAM: [50, 38], RAM: [81, 36], ST: [50, 18] },
  "4-4-2": { ...BACK4, LM: [13, 45], LCM: [38, 51], RCM: [62, 51], RM: [87, 45], LST: [38, 21], RST: [62, 21] },
  "3-5-2": { ...BACK3, LWB: [10, 49], LCM: [31, 52], CM: [50, 56], RCM: [69, 52], RWB: [90, 49], LST: [38, 21], RST: [62, 21] },
  "3-4-3": { ...BACK3, LWB: [11, 50], LCM: [38, 54], RCM: [62, 54], RWB: [89, 50], LW: [20, 26], ST: [50, 19], RW: [80, 26] },
};
export const FORMATIONS = Object.keys(SLOT_XY);

const ROLE_ROW: Record<Role, number> = { GK: 90, CB: 74, FB: 64, CM: 51, AW: 34, ST: 19 };

/** Positions for a team: by slot for a formation, otherwise one row per role, spread evenly. */
export function positions(players: PlayerOut[], formation: string | null | undefined): Map<number, XY> {
  const out = new Map<number, XY>();
  const map = formation ? SLOT_XY[formation] : undefined;
  if (map && players.every((p) => map[p.slot])) {
    players.forEach((p) => out.set(p.player_id, map[p.slot]));
    return out;
  }
  const byRole = new Map<Role, PlayerOut[]>();
  players.forEach((p) => byRole.set(p.role, [...(byRole.get(p.role) ?? []), p]));
  byRole.forEach((group, role) => {
    group.forEach((p, i) => out.set(p.player_id, [((i + 1) / (group.length + 1)) * 100, ROLE_ROW[role]]));
  });
  return out;
}
