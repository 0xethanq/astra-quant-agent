import { enAdminShell } from './shell';
import { enAdminLogin } from './login';
import { enAdminOverview } from './overview';
import { enAdminPolicySnapshot } from './policySnapshot';
import { enAdminPromptStudio } from './promptStudio';
import { enAdminAdminSys } from './adminSys';
import { enAdminGateway } from './gateway';
import { enAdminAbout } from './about';
import { enAdminBackup } from './backup';
import { enAdminAudit } from './audit';
import { enAdminAgents } from './agents';
import { enAdminCouncil } from './council';
import { enAdminLlm } from './llm';
import { enAdminSecurity } from './security';
import { enAdminDecisions } from './decisions';
import { enAdminEvolution } from './evolution';
import { enAdminNotify } from './notify';
import { enAdminRisk } from './risk';

/** 控制台文案聚合（2026-09-30：`plugins` / `legacy` 随页面删除而移除） */
export const enAdmin = {
  shell: enAdminShell,
  login: enAdminLogin,
  overview: enAdminOverview,
  policySnapshot: enAdminPolicySnapshot,
  promptStudio: enAdminPromptStudio,
  adminsys: enAdminAdminSys,
  gateway: enAdminGateway,
  about: enAdminAbout,
  backup: enAdminBackup,
  audit: enAdminAudit,
  agents: enAdminAgents,
  council: enAdminCouncil,
  llm: enAdminLlm,
  security: enAdminSecurity,
  decisions: enAdminDecisions,
  evolution: enAdminEvolution,
  notify: enAdminNotify,
  risk: enAdminRisk,
};
