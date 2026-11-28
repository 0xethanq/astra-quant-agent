import { zhAdminShell } from './shell';
import { zhAdminLogin } from './login';
import { zhAdminAgent } from './agent';
import { zhAdminPolicySnapshot } from './policySnapshot';
import { zhAdminAdminSys } from './adminSys';
import { zhAdminAbout } from './about';
import { zhAdminBackup } from './backup';
import { zhAdminAudit } from './audit';
import { zhAdminLlm } from './llm';
import { zhAdminSecurity } from './security';
import { zhAdminDecisions } from './decisions';
import { zhAdminNotify } from './notify';

/** 控制台文案聚合：Agent-First 精简后保留 AI 指挥台与 5 个高频系统运维页及嵌入式子页。 */
export const zhAdmin = {
  shell: zhAdminShell,
  login: zhAdminLogin,
  agent: zhAdminAgent,
  policySnapshot: zhAdminPolicySnapshot,
  adminsys: zhAdminAdminSys,
  about: zhAdminAbout,
  backup: zhAdminBackup,
  audit: zhAdminAudit,
  llm: zhAdminLlm,
  security: zhAdminSecurity,
  decisions: zhAdminDecisions,
  notify: zhAdminNotify,
};
