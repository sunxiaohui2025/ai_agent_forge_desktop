<template>
  <div class="plugins">
    <el-tabs v-model="tab" class="pg-tabs">
      <el-tab-pane name="skills">
        <template #label>
          <span class="tab-label">技能</span>
        </template>
        <SkillsView />
      </el-tab-pane>
      <el-tab-pane name="mcp">
        <template #label>
          <span class="tab-label">MCP</span>
        </template>
        <MCPView />
      </el-tab-pane>
      <el-tab-pane name="cli-apps">
        <template #label>
          <span class="tab-label">连接应用</span>
        </template>
        <CliAppsView />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import SkillsView from '@/views/admin/Skills.vue'
import MCPView from '@/views/admin/MCP.vue'
import CliAppsView from '@/views/admin/CliApps.vue'

const route = useRoute()
const VALID_TABS = ['skills', 'mcp', 'cli-apps']
const tab = ref(VALID_TABS.includes(route.query.tab as string) ? (route.query.tab as string) : 'skills')
watch(() => route.query.tab, (t) => {
  if (VALID_TABS.includes(t as string)) tab.value = t as string
})
</script>

<style scoped>
.plugins {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
  padding: 18px 22px;
}
.pg-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 18px;
}
.pg-tabs :deep(.el-tabs__header) {
  margin: 0;
}
.pg-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}
.pg-tabs :deep(.el-tabs__nav) {
  gap: 4px;
  padding: 4px;
  border-radius: 999px;
  background: #f1f1ef;
}
.pg-tabs :deep(.el-tabs__item) {
  height: 30px;
  padding: 0 14px !important;
  border-radius: 999px;
  color: #777770;
  font-weight: 650;
}
.pg-tabs :deep(.el-tabs__item.is-active) {
  background: #fff;
  color: #232321;
}
.pg-tabs :deep(.el-tabs__active-bar) {
  display: none;
}
.tab-label { display: inline-flex; align-items: center; gap: 6px; }
.pg-tabs :deep(.el-tabs__content) {
  flex: 1;
  overflow: auto;
  padding-top: 14px;
}
.pg-tabs :deep(.page) {
  padding: 0 0 40px;
  max-width: 100%;
}
.pg-tabs :deep(.page-head) {
  margin-bottom: 18px;
}
.pg-tabs :deep(.page-title) {
  font-size: 22px;
}
</style>
