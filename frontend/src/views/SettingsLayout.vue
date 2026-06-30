<template>
  <div class="set-shell">
    <div class="set-main">
      <!-- Left settings menu -->
      <nav class="set-nav">
        <div class="set-nav-top">
          <button class="back-btn" @click="goBack">
            <el-icon :size="15"><Back /></el-icon>
            <span>返回应用</span>
          </button>
        </div>
        <div class="set-nav-group">通用</div>
        <router-link to="/settings/general" class="set-nav-item" active-class="active">
          <el-icon :size="15"><Setting /></el-icon><span>通用</span>
        </router-link>
        <router-link to="/settings/pets" class="set-nav-item" active-class="active">
          <el-icon :size="15"><Star /></el-icon><span>Pets</span>
        </router-link>
        <router-link to="/settings/models" class="set-nav-item" active-class="active">
          <el-icon :size="15"><Cpu /></el-icon><span>模型 / Provider</span>
        </router-link>

        <div class="set-nav-group">系统</div>
        <router-link to="/settings/health" class="set-nav-item" active-class="active">
          <el-icon :size="15"><FirstAidKit /></el-icon><span>健康检查</span>
        </router-link>
        <router-link to="/settings/usage" class="set-nav-item" active-class="active">
          <el-icon :size="15"><DataLine /></el-icon><span>用量统计</span>
        </router-link>
        <router-link to="/settings/logs" class="set-nav-item" active-class="active">
          <el-icon :size="15"><Document /></el-icon><span>调用记录</span>
        </router-link>
        <router-link to="/settings/bridge" class="set-nav-item" active-class="active">
          <el-icon :size="15"><Share /></el-icon><span>远程桥接</span>
        </router-link>
        <router-link to="/settings/about" class="set-nav-item" active-class="active">
          <el-icon :size="15"><InfoFilled /></el-icon><span>关于</span>
        </router-link>
      </nav>

      <!-- Right content -->
      <section class="set-content">
        <router-view />
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
const router = useRouter()
function goBack() { router.push('/chat') }
</script>

<style scoped>
.set-shell { display: flex; flex-direction: column; height: 100vh; background: #ffffff; }

.back-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 10px; border: 0; border-radius: var(--m-radius);
  background: transparent; cursor: pointer; font-size: 13px; color: var(--m-text);
  transition: background .12s, border-color .12s;
}
.back-btn:hover { background: #e9e9e7; border-color: var(--m-border-strong); }

.set-main { flex: 1; display: flex; min-height: 0; }

.set-nav {
  width: 248px; flex-shrink: 0; padding: 0 12px 16px;
  border-right: 0; background: rgb(251, 250, 251);
  overflow: auto;
}
.set-nav-top {
  padding: 48px 0 2px 1px;
  -webkit-app-region: drag;
}
.set-nav-group {
  font-size: 11px; font-weight: 650; color: var(--m-text-tertiary);
  letter-spacing: .05em; padding: 14px 10px 6px;
}
.set-nav-group:first-child { padding-top: 4px; }
.set-nav-item {
      margin-top: 5px;
  display: flex; align-items: center; gap: 10px;
  padding: 7px 10px; border-radius: var(--m-radius);
  font-size: 13px; color: var(--m-text); text-decoration: none;
  transition: background .12s;
}
.set-nav-item:hover { background: #e9e9e7; }
.set-nav-item.active { background: #e4e4e2; box-shadow: none; font-weight: 650; }
.set-nav-item.active :deep(.el-icon) { color: var(--m-primary); }

.set-content {
  flex: 1;
  min-width: 0;
  overflow: auto;
  background: #ffffff;
  position: relative;
}
.set-content::before {
  content: "";
  position: sticky;
  top: 0;
  display: block;
  height: 32px;
  margin-bottom: -32px;
  z-index: 2;
  -webkit-app-region: drag;
}
.set-content :deep(.page) {
  width: 100%;
  max-width: 1040px;
  min-height: 100%;
  margin: 0 auto;
  padding: 56px 72px 88px;
  background: #ffffff;
}
.set-nav button,
.set-nav a,
.set-content :deep(button),
.set-content :deep(a),
.set-content :deep(input),
.set-content :deep(textarea),
.set-content :deep(select),
.set-content :deep(.el-select),
.set-content :deep(.el-input),
.set-content :deep(.el-textarea),
.set-content :deep(.el-switch),
.set-content :deep(.el-slider) {
  -webkit-app-region: no-drag;
}
.set-content :deep(.page-head) {
  align-items: flex-start;
  margin: 0 0 34px;
  min-height: 34px;
}
.set-content :deep(.page-head h2),
.set-content :deep(.page-title) {
  font-size: 28px;
  font-weight: 760;
  line-height: 1.18;
  letter-spacing: 0;
  color: #20201e;
}
.set-content :deep(.page-head .el-button),
.set-content :deep(.page-head > .el-button),
.set-content :deep(.page-head > div .el-button) {
  border-radius: 999px !important;
  height: 34px;
  padding: 0 14px;
}

/* Desktop settings content: soft lists instead of admin tables. */
.set-content :deep(.el-table) {
  border: 0 !important;
  border-radius: 16px !important;
  background: #ffffff !important;
  box-shadow: 0 0 0 1px #eeeeeb inset !important;
}
.set-content :deep(.el-table__inner-wrapper::before),
.set-content :deep(.el-table__border-left-patch) {
  display: none !important;
}
.set-content :deep(.el-table th.el-table__cell) {
  background: #ffffff !important;
  color: #989891 !important;
  font-size: 12px;
  font-weight: 650 !important;
  border-bottom: 1px solid #f0f0ed !important;
  padding: 12px 0;
}
.set-content :deep(.el-table td.el-table__cell) {
  border-bottom: 1px solid #f2f2ef !important;
  padding: 14px 0;
}
.set-content :deep(.el-table__body tr:hover > td.el-table__cell) {
  background: #fafaf8 !important;
}
.set-content :deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background: #ffffff !important;
}
.set-content :deep(.el-table .cell) {
  line-height: 1.45;
}
.set-content :deep(.row-actions .el-button),
.set-content :deep(.el-button.is-text) {
  color: #676761;
}

/* Form-like sections become native desktop setting groups. */
.set-content :deep(.set-rows),
.set-content :deep(.about-card),
.set-content :deep(.section),
.set-content :deep(.ch-config),
.set-content :deep(.cards),
.set-content :deep(.bars) {
  border-color: #eeeeeb !important;
}
.set-content :deep(.set-rows),
.set-content :deep(.about-card),
.set-content :deep(.ch-config) {
  border: 1px solid #eeeeeb;
  border-radius: 16px;
  background: #ffffff;
  box-shadow: none;
}
.set-content :deep(.set-row) {
  padding: 18px 18px;
  background: #ffffff;
  border-bottom-color: #f1f1ee;
}
.set-content :deep(.set-row-title),
.set-content :deep(.row-title),
.set-content :deep(.ch-title),
.set-content :deep(.section-title),
.set-content :deep(.card-title) {
  color: #272724;
  font-weight: 700;
}
.set-content :deep(.set-row-desc),
.set-content :deep(.about-tag),
.set-content :deep(.ch-desc),
.set-content :deep(.bridge-lead),
.set-content :deep(.card-sub) {
  color: #8a8a84;
}

/* Statistics cards and bridge tabs: airy cards with minimal chrome. */
.set-content :deep(.cards) {
  gap: 14px;
}
.set-content :deep(.card) {
  border: 1px solid #eeeeeb;
  border-radius: 16px;
  background: #ffffff;
  padding: 18px;
}
.set-content :deep(.card-value) {
  font-size: 28px;
  letter-spacing: 0;
}
.set-content :deep(.section) {
  margin-bottom: 28px;
}
.set-content :deep(.ch-tab) {
  border: 0;
  background: transparent;
  border-radius: 12px;
}
.set-content :deep(.ch-tab:hover),
.set-content :deep(.ch-tab.active) {
  background: #f1f1ef;
  box-shadow: none;
}
.set-content :deep(.callback-box),
.set-content :deep(.qa-block),
.set-content :deep(.tool-card),
.set-content :deep(.preset-card) {
  border: 0 !important;
  background: #f6f6f3 !important;
  border-radius: 14px !important;
}

@media (max-width: 1180px) {
  .set-content :deep(.page) {
    padding-left: 42px;
    padding-right: 42px;
  }
}
</style>
