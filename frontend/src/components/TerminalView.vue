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

const props = withDefaults(defineProps<{
  cwd: string | null
  sessionKey: string | number
  active?: boolean
  receiveExternal?: boolean
}>(), {
  active: true,
  receiveExternal: true,
})
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
  if (!props.receiveExternal) return
  writeToActiveTerminal((e as CustomEvent).detail?.data || '')
}

function fitTerminal() {
  if (!term || !fit) return
  const d = (window as any).desktop
  fit.fit()
  if (d?.term && termId) d.term.resize(termId, term.cols, term.rows)
}

function startTerminal() {
  if (!isDesktop || !host.value) return
  disposeTerminal()
  termId = 'term-' + props.sessionKey + '-' + Date.now()
  term = new Terminal({
    fontSize: 13,
    fontFamily: "Menlo, Monaco, 'Courier New', monospace",
    fontWeight: 'normal',
    letterSpacing: 0,
    lineHeight: 1.12,
    theme: {
      background: '#ffffff',
      foreground: '#1c1c1a',
      cursor: '#1c1c1a',
      selectionBackground: '#d7d7d2',
      black: '#1c1c1a',
      red: '#b5392f',
      green: '#2f8a52',
      yellow: '#a8741a',
      blue: '#3a6fb0',
      magenta: '#7a6cae',
      cyan: '#237c83',
      white: '#f7f7f4',
      brightBlack: '#8a897f',
      brightRed: '#c94a42',
      brightGreen: '#3f9c62',
      brightYellow: '#bd8430',
      brightBlue: '#4b7fc0',
      brightMagenta: '#8b7ec0',
      brightCyan: '#33939a',
      brightWhite: '#ffffff',
    },
    cursorBlink: true,
  })
  fit = new FitAddon()
  term.loadAddon(fit)
  term.open(host.value)
  setTimeout(fitTerminal, 30)

  const d = (window as any).desktop
  d.term.create({ id: termId, cwd: props.cwd, cols: term.cols, rows: term.rows })
  term.onData((data: string) => d.term.write(termId, data))
  offData = d.term.onData(({ id, data }: any) => { if (id === termId) term?.write(data) })
  offExit = d.term.onExit(({ id }: any) => { if (id === termId) term?.write('\r\n[进程已退出]\r\n') })
  for (const data of pendingWrites.splice(0)) d.term.write(termId, data)

  ro = new ResizeObserver(() => {
    fitTerminal()
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
watch(() => props.active, (active) => {
  if (active) setTimeout(fitTerminal, 30)
})
</script>

<style scoped>
.term-wrap { height: 100%; background: #ffffff; }
.term-host { height: 100%; padding: 6px 8px; box-sizing: border-box; background: #ffffff; }
.term-hint { padding: 24px; color: var(--m-text-tertiary, #9a9a93); font-size: 13px; text-align: center; }
.term-host :deep(.xterm) {
  font-family: Menlo, Monaco, 'Courier New', monospace !important;
  font-feature-settings: "liga" 0;
  letter-spacing: 0 !important;
}
.term-host :deep(.xterm-viewport),
.term-host :deep(.xterm-screen) {
  background: #ffffff !important;
}
</style>
