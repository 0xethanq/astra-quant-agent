import { zhAdminShell } from './shell';
import { zhAdminLogin } from './login';
import { zhAdminOverview } from './overview';
import { zhAdminPolicySnapshot } from './policySnapshot';
import { zhAdminPromptStudio } from './promptStudio';
import { zhAdminAdminSys } from './adminSys';
import { zhAdminGateway } from './gateway';
import { zhAdminAbout } from './about';
import { zhAdminBackup } from './backup';
import { zhAdminAudit } from './audit';
import { zhAdminAgents } from './agents';
import { zhAdminCouncil } from './council';
import { zhAdminInterceptors } from './interceptors';
import { zhAdminLlm } from './llm';
import { zhAdminSecurity } from './security';
import { zhAdminDecisions } from './decisions';
import { zhAdminEvolution } from './evolution';
import { zhAdminNotify } from './notify';
import { zhAdminRisk } from './risk';

/** 控制台文案聚合：各页键位随页面重建逐页追加。
 * 2026-09-30 后台精简：`plugins`（内置插件清单页已删）与 `legacy`（旧版跳转页已删）两个命名空间随页面一起移除。 */
export const zhAdmin = {
  shell: zhAdminShell,
  login: zhAdminLogin,
  overview: zhAdminOverview,
  policySnapshot: zhAdminPolicySnapshot,
  promptStudio: zhAdminPromptStudio,
  adminsys: zhAdminAdminSys,
  gateway: zhAdminGateway,
  about: zhAdminAbout,
  backup: zhAdminBackup,
  audit: zhAdminAudit,
  agents: zhAdminAgents,
  council: zhAdminCouncil,
  interceptors: zhAdminInterceptors,
  llm: zhAdminLlm,
  security: zhAdminSecurity,
  decisions: zhAdminDecisions,
  evolution: zhAdminEvolution,
  notify: zhAdminNotify,
  risk: zhAdminRisk,
};
