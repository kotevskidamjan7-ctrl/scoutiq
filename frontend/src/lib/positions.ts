// Where a Transfermarkt position sits on the pitch (x, y in % of a vertical pitch, attack upwards).
import type { Role } from "./api";

export const POSITION_XY: Record<string, [number, number]> = {
  "Goalkeeper": [50, 90],
  "Centre-Back": [50, 75],
  "Left-Back": [16, 67],
  "Right-Back": [84, 67],
  "Defensive Midfield": [50, 60],
  "Central Midfield": [50, 49],
  "Attacking Midfield": [50, 37],
  "Left Midfield": [17, 47],
  "Right Midfield": [83, 47],
  "Left Winger": [18, 28],
  "Right Winger": [82, 28],
  "Second Striker": [50, 26],
  "Centre-Forward": [50, 17],
};

const ROLE_XY: Record<Role, [number, number]> = {
  GK: [50, 90], CB: [50, 75], FB: [16, 67], CM: [50, 49], AW: [18, 28], ST: [50, 17],
};

export function positionXY(position: string | null | undefined, role: Role | null | undefined): [number, number] | null {
  if (position && POSITION_XY[position]) return POSITION_XY[position];
  return role ? ROLE_XY[role] : null;
}
