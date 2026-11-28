import { enAdminShell } from './shell';
import { enAdminLogin } from './login';
import { enAdminAgent } from './agent';
import { enAdminStrategy } from './strategy';
import { enAdminPolicySnapshot } from './policySnapshot';
import { enAdminAdminSys } from './adminSys';
import { enAdminAbout } from './about';
import { enAdminBackup } from './backup';
import { enAdminAudit } from './audit';
import { enAdminLlm } from './llm';
import { enAdminSecurity } from './security';
import { enAdminDecisions } from './decisions';
import { enAdminNotify } from './notify';

/** Admin console copy bundle after Agent-First consolidation. */
export const enAdmin = {
  shell: enAdminShell,
  login: enAdminLogin,
  agent: enAdminAgent,
  strategy: enAdminStrategy,
  policySnapshot: enAdminPolicySnapshot,
  adminsys: enAdminAdminSys,
  about: enAdminAbout,
  backup: enAdminBackup,
  audit: enAdminAudit,
  llm: enAdminLlm,
  security: enAdminSecurity,
  decisions: enAdminDecisions,
  notify: enAdminNotify,
};
