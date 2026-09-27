import { enCommon } from './common';
import { enChart } from './chart';
import { enNav } from './nav';
import { enDash } from './dash';
import { enAdmin } from './admin';
import { enDocs } from './docs';
import { enLanding } from './landing';

export const enUS = {
  ...enCommon,
  chart: enChart,
  nav: enNav,
  dash: enDash,
  admin: enAdmin,
  docs: enDocs,
  landing: enLanding,
};
