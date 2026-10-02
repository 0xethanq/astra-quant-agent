import { ref, onMounted } from 'vue';
import { useApi } from './useApi';

export interface UpdateNoticeStatus {
  version: string;
  local: string;
  remote: string;
  branch: string;
  behind: number;
  ahead: number;
  dirty: boolean;
  update_available: boolean;
  commits: string[];
  checked_at: number;
}

const updateAvailable = ref(false);
const behindCount = ref(0);
const remoteCommit = ref('');
const commits = ref<string[]>([]);
const lastChecked = ref(0);
const loading = ref(false);

export function useUpdateNotice() {
  const { api } = useApi();

  async function check(force = false) {
    const now = Date.now();
    if (!force && lastChecked.value > 0 && now - lastChecked.value < 300000) {
      return;
    }
    try {
      loading.value = true;
      const res = await api<UpdateNoticeStatus>('/api/v1/system/update-status');
      if (res) {
        updateAvailable.value = Boolean(res.update_available);
        behindCount.value = Number(res.behind || 0);
        remoteCommit.value = String(res.remote || '');
        commits.value = Array.isArray(res.commits) ? res.commits : [];
        lastChecked.value = now;
      }
    } catch {
      // Non-blocking fallback
    } finally {
      loading.value = false;
    }
  }

  onMounted(() => {
    check(false);
  });

  return {
    updateAvailable,
    behindCount,
    remoteCommit,
    commits,
    loading,
    check,
  };
}
