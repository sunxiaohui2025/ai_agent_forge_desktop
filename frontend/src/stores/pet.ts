import { defineStore } from 'pinia'

export type PetKind = 'cube' | 'terminal' | 'cat' | 'capsule' | 'orbit' | 'spark' | 'jelly' | 'cloud'

const KEY_ENABLED = 'h3c-agent.pet.enabled'
const KEY_KIND = 'h3c-agent.pet.kind'
const isBrowser = typeof window !== 'undefined'

function readEnabled() {
  if (!isBrowser) return true
  const v = localStorage.getItem(KEY_ENABLED)
  return v == null ? true : v === 'true'
}

function readKind(): PetKind {
  if (!isBrowser) return 'cube'
  const v = localStorage.getItem(KEY_KIND) as PetKind | null
  return v && ['cube', 'terminal', 'cat', 'capsule', 'orbit', 'spark', 'jelly', 'cloud'].includes(v) ? v : 'cube'
}

export const PETS: Array<{ kind: PetKind; name: string; desc: string }> = [
  { kind: 'cube', name: '小方块助手', desc: 'Claude 陶土色系，克制的工具感。' },
  { kind: 'terminal', name: '终端小机器人', desc: '深青蓝屏幕，适合开发工作台。' },
  { kind: 'cat', name: '像素猫耳助手', desc: '紫色猫耳，活泼但不喧闹。' },
  { kind: 'capsule', name: '胶囊小精灵', desc: '绿色胶囊，圆润轻快。' },
  { kind: 'orbit', name: '轨道小星球', desc: '蓝橙撞色，像一颗会探头的小行星。' },
  { kind: 'spark', name: '电波小豆', desc: '明黄色天线款，适合需要一点精神的时候。' },
  { kind: 'jelly', name: '霓虹水母', desc: '青粉渐变感，轻轻浮动，桌面更有呼吸。' },
  { kind: 'cloud', name: '像素云团', desc: '天空蓝和薄荷绿，柔和一点的陪伴感。' },
]

export const usePet = defineStore('pet', {
  state: () => ({
    enabled: readEnabled(),
    kind: readKind(),
  }),
  actions: {
    setEnabled(v: boolean) {
      this.enabled = v
      if (isBrowser) localStorage.setItem(KEY_ENABLED, String(v))
    },
    select(kind: PetKind) {
      this.kind = kind
      this.enabled = true
      if (isBrowser) {
        localStorage.setItem(KEY_KIND, kind)
        localStorage.setItem(KEY_ENABLED, 'true')
      }
    },
  },
})
