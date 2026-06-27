<template>
  <div class="term-wrap">
    <div v-if="!isDesktop" class="term-hint">终端仅在桌面客户端可用</div>
    <div v-else ref="host" class="term-host"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

const props = defineProps<{ cwd: string | null; sessionKey: string | number }>()
const host = ref<HTMLElement | null>(null)
const isDesktop = typeof window !== 'undefined' && (window as any).desktop?.isDesktop === true

let term: Terminal | null = null
let fit: FitAddon | null = null
let offData: (() => void) | null = null
let offExit: (() => void) | null = null
let termId = ''
let ro: ResizeObserver | null = null
let pendingWrites: string[] = []

function writeToActiveTerminal(data: string) {
  if (!data) return
  if (termId && (window as any).desktop) {
    ;(window as any).desktop.term.write(termId, data)
  } else {
    pendingWrites.push(data)
  }
}

function onExternalWrite(e: Event) {
  writeToActiveTerminal((e as CustomEvent).detail?.data || '')
}

function startTerminal() {
  if (!isDesktop || !host.value) return
  disposeTerminal()
  termId = 'term-' + props.sessionKey + '-' + Date.now()
  term = new Terminal({
    fontSize: 12.5,
    fontFamily: "'Roboto Mono', Menlo, monospace",
    theme: { background: '#1c1c1a', foreground: '#e7e7e4', cursor: '#e7e7e4' },
    cursorBlink: true,
  })
  fit = new FitAddon()
  term.loadAddon(fit)
  term.open(host.value)
  setTimeout(() => fit?.fit(), 30)

  const d = (window as any).desktop
  d.term.create({ id: termId, cwd: props.cwd, cols: term.cols, rows: term.rows })
  term.onData((data: string) => d.term.write(termId, data))
  offData = d.term.onData(({ id, data }: any) => { if (id === termId) term?.write(data) })
  offExit = d.term.onExit(({ id }: any) => { if (id === termId) term?.write('\r\n[进程已退出]\r\n') })
  for (const data of pendingWrites.splice(0)) d.term.write(termId, data)

  ro = new ResizeObserver(() => {
    fit?.fit()
    if (term) d.term.resize(termId, term.cols, term.rows)
  })
  ro.observe(host.value)
}

function disposeTerminal() {
  offData?.(); offExit?.()
  ro?.disconnect(); ro = null
  if (termId && (window as any).desktop) (window as any).desktop.term.kill(termId)
  term?.dispose(); term = null; fit = null; termId = ''
}

onMounted(startTerminal)
onMounted(() => window.addEventListener('workbuddy:terminal-write', onExternalWrite))
onBeforeUnmount(() => {
  window.removeEventListener('workbuddy:terminal-write', onExternalWrite)
  disposeTerminal()
})
// Restart the shell when the working directory changes (switch project).
watch(() => props.cwd, () => startTerminal())
</script>

<style scoped>
.term-wrap { height: 100%; background: #1c1c1a; }
.term-host { height: 100%; padding: 6px; box-sizing: border-box; }
.term-hint { padding: 24px; color: var(--m-text-tertiary, #9a9a93); font-size: 13px; text-align: center; }
</style>
