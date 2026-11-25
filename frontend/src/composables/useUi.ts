/** 全局 UI 浮层状态：关于弹窗 / 返佣通道弹窗 / 决策透视抽屉 / 决策轨迹 */
import { ref } from 'vue';

export const aboutOpen = ref(false);
export const rebateOpen = ref(false);
export const peekOpen = ref(false);
export const trajectoryOpen = ref(false);

export function useUi() {
  return { aboutOpen, rebateOpen, peekOpen, trajectoryOpen };
}
