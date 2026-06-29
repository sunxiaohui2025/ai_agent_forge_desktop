<template>
  <div v-if="visible" class="home-pet" :class="[`pet-${activeKind}`]" aria-hidden="true">
    <div class="pet-body">
      <span class="eye l" />
      <span class="eye r" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { usePet } from '@/stores/pet'
import { computed } from 'vue'
import type { PetKind } from '@/stores/pet'

const props = defineProps<{ kind?: PetKind; preview?: boolean }>()
const pet = usePet()
const activeKind = computed(() => props.kind || pet.kind)
const visible = computed(() => props.preview || pet.enabled)
</script>

<style scoped>
.home-pet {
  width: 92px;
  height: 86px;
  display: grid;
  place-items: end center;
  pointer-events: none;
  animation: pet-peek 13.5s ease-in-out infinite;
}
.pet-body {
  position: relative;
  image-rendering: pixelated;
}
.eye {
  position: absolute;
  width: 7px;
  height: 9px;
  background: #fff1dc;
  border-radius: 2px;
  animation: pet-blink 4.2s steps(1) infinite;
}
.eye.r { animation-delay: .06s; }

@keyframes pet-peek {
  0%, 10%, 100% { transform: translateY(58px); }
  18%, 88% { transform: translateY(0); }
  92% { transform: translateY(10px); }
  96% { transform: translateY(58px); }
}
@keyframes pet-blink {
  0%, 88%, 94%, 100% { transform: scaleY(1); }
  91% { transform: scaleY(.12); }
}
@keyframes pet-bob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}
@keyframes pet-breathe {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.04, .98); }
}
@keyframes pet-screen-pulse {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.15); }
}
@keyframes pet-ear {
  0%, 80%, 100% { transform: rotate(45deg); }
  86% { transform: rotate(38deg); }
}
@keyframes pet-wiggle {
  0%, 100% { transform: rotate(-2deg); }
  50% { transform: rotate(2deg); }
}
@keyframes pet-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-5px); }
}

.pet-cube .pet-body {
  width: 62px;
  height: 48px;
  background: #c15f3f;
  border-radius: 12px 12px 10px 10px;
  box-shadow: inset 0 4px 0 rgba(255,246,236,.22), 0 10px 0 #8f3f2c;
  animation: pet-bob 2.8s ease-in-out infinite;
}
.pet-cube .pet-body::before {
  content: "";
  position: absolute;
  left: 9px;
  right: 9px;
  top: -10px;
  height: 10px;
  background: #df8a63;
  border-radius: 8px 8px 0 0;
}
.pet-cube .eye.l { left: 18px; top: 20px; }
.pet-cube .eye.r { right: 18px; top: 20px; }

.pet-terminal .pet-body {
  width: 66px;
  height: 52px;
  background: #172d36;
  border-radius: 8px;
  border: 5px solid #4f7580;
  box-shadow: 0 8px 0 #0d1c22;
  animation: pet-screen-pulse 3.6s ease-in-out infinite;
}
.pet-terminal .pet-body::before {
  content: "";
  position: absolute;
  left: 28px;
  top: -18px;
  width: 3px;
  height: 16px;
  background: #4f7580;
  box-shadow: 8px -4px 0 0 #4f7580;
}
.pet-terminal .eye { width: 9px; height: 7px; background: #7df7d4; top: 20px; }
.pet-terminal .eye.l { left: 17px; }
.pet-terminal .eye.r { right: 17px; }

.pet-cat .pet-body {
  width: 62px;
  height: 48px;
  background: #6d5dd3;
  border-radius: 16px 16px 12px 12px;
  box-shadow: 0 9px 0 #43388f;
  animation: pet-bob 2.6s ease-in-out infinite;
}
.pet-cat .pet-body::before,
.pet-cat .pet-body::after {
  content: "";
  position: absolute;
  top: -14px;
  width: 22px;
  height: 22px;
  background: #6d5dd3;
  transform: rotate(45deg);
  border-radius: 4px;
  animation: pet-ear 3.2s ease-in-out infinite;
}
.pet-cat .pet-body::before { left: 5px; }
.pet-cat .pet-body::after { right: 5px; animation-delay: .18s; }
.pet-cat .eye { background: #ffd65a; }
.pet-cat .eye.l { left: 18px; top: 20px; }
.pet-cat .eye.r { right: 18px; top: 20px; }

.pet-capsule .pet-body {
  width: 58px;
  height: 64px;
  background: #2f8a52;
  border-radius: 28px;
  box-shadow: inset 0 6px 0 rgba(255,255,255,.18), 0 10px 0 #1d5d37;
  animation: pet-breathe 3.2s ease-in-out infinite;
}
.pet-capsule .pet-body::before {
  content: "";
  position: absolute;
  left: 13px;
  right: 13px;
  bottom: -10px;
  height: 10px;
  background: #a7e8bd;
  border-radius: 0 0 10px 10px;
}
.pet-capsule .eye { background: #eaff73; }
.pet-capsule .eye.l { left: 16px; top: 28px; }
.pet-capsule .eye.r { right: 16px; top: 28px; }

.pet-orbit .pet-body {
  width: 58px;
  height: 58px;
  background: #3f7df6;
  border-radius: 50%;
  box-shadow: inset 0 6px 0 rgba(255,255,255,.2), 0 9px 0 #244da8;
  animation: pet-bob 3s ease-in-out infinite;
}
.pet-orbit .pet-body::before {
  content: "";
  position: absolute;
  left: -13px;
  right: -13px;
  top: 27px;
  height: 9px;
  border-radius: 999px;
  background: #ff9f43;
  transform: rotate(-14deg);
  box-shadow: inset 0 2px 0 rgba(255,255,255,.35);
}
.pet-orbit .pet-body::after {
  content: "";
  position: absolute;
  right: 7px;
  top: 8px;
  width: 12px;
  height: 12px;
  border-radius: 4px;
  background: #78f0d4;
}
.pet-orbit .eye { background: #ffffff; top: 22px; z-index: 1; }
.pet-orbit .eye.l { left: 17px; }
.pet-orbit .eye.r { right: 17px; }

.pet-spark .pet-body {
  width: 56px;
  height: 50px;
  background: #f4c430;
  border-radius: 14px 14px 12px 12px;
  box-shadow: inset 0 5px 0 rgba(255,255,255,.26), 0 9px 0 #b77612;
  animation: pet-wiggle 2.6s ease-in-out infinite;
}
.pet-spark .pet-body::before {
  content: "";
  position: absolute;
  left: 26px;
  top: -18px;
  width: 4px;
  height: 17px;
  border-radius: 999px;
  background: #b77612;
  box-shadow: -11px -2px 0 -1px #ff6b6b, 11px -2px 0 -1px #2dd4bf;
}
.pet-spark .pet-body::after {
  content: "";
  position: absolute;
  left: 9px;
  right: 9px;
  bottom: 9px;
  height: 5px;
  border-radius: 999px;
  background: rgba(183,118,18,.38);
}
.pet-spark .eye { background: #2b2b28; width: 6px; height: 8px; top: 18px; }
.pet-spark .eye.l { left: 17px; }
.pet-spark .eye.r { right: 17px; }

.pet-jelly .pet-body {
  width: 62px;
  height: 52px;
  background: #18b6c7;
  border-radius: 28px 28px 14px 14px;
  box-shadow: inset 0 6px 0 rgba(255,255,255,.24), 0 8px 0 #0c7480;
  animation: pet-float 3.4s ease-in-out infinite;
}
.pet-jelly .pet-body::before {
  content: "";
  position: absolute;
  left: 10px;
  right: 10px;
  bottom: -9px;
  height: 11px;
  background:
    linear-gradient(90deg, #ff80b5 0 18%, transparent 18% 27%, #ff80b5 27% 45%, transparent 45% 55%, #ff80b5 55% 73%, transparent 73% 82%, #ff80b5 82% 100%);
  border-radius: 0 0 8px 8px;
}
.pet-jelly .pet-body::after {
  content: "";
  position: absolute;
  left: 12px;
  right: 12px;
  top: 10px;
  height: 7px;
  border-radius: 999px;
  background: rgba(255,255,255,.28);
}
.pet-jelly .eye { background: #eaffff; top: 25px; }
.pet-jelly .eye.l { left: 19px; }
.pet-jelly .eye.r { right: 19px; }

.pet-cloud .pet-body {
  width: 66px;
  height: 42px;
  background: #8fd7ff;
  border-radius: 18px;
  box-shadow: 0 8px 0 #4a9fd1;
  animation: pet-breathe 3.8s ease-in-out infinite;
}
.pet-cloud .pet-body::before,
.pet-cloud .pet-body::after {
  content: "";
  position: absolute;
  bottom: 14px;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: #8fd7ff;
}
.pet-cloud .pet-body::before { left: 7px; background: #93f0c5; }
.pet-cloud .pet-body::after { right: 9px; }
.pet-cloud .eye { background: #24556d; width: 6px; height: 7px; top: 17px; z-index: 1; }
.pet-cloud .eye.l { left: 21px; }
.pet-cloud .eye.r { right: 21px; }
</style>
