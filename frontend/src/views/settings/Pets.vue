<template>
  <div class="page pets-page">
    <div class="page-head">
      <div>
        <span class="page-title">Pets</span>
        <p class="page-sub">选择首页对话框旁边的像素伙伴。默认开启，并使用小方块助手。</p>
      </div>
    </div>

    <section class="pet-panel">
      <div class="pet-toolbar">
        <div>
          <div class="toolbar-title">首页Pets</div>
          <div class="toolbar-desc">{{ pet.enabled ? '已开启，Pets会在首页对话框右上角出现。' : '已关闭，首页不显示Pets。' }}</div>
        </div>
        <el-switch :model-value="pet.enabled" @change="pet.setEnabled(Boolean($event))" />
      </div>

      <div class="pet-list">
        <article
          v-for="item in PETS"
          :key="item.kind"
          :class="['pet-row', { selected: pet.kind === item.kind && pet.enabled }]"
          @click="pet.select(item.kind)"
        >
          <div class="pet-preview">
            <HomePet :kind="item.kind" preview />
          </div>
          <div class="pet-copy">
            <div class="pet-name">{{ item.name }}</div>
            <div class="pet-desc">{{ item.desc }}</div>
          </div>
          <button class="pet-select">{{ pet.kind === item.kind && pet.enabled ? '已唤醒' : '唤醒宠物' }}</button>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { PETS, usePet } from '@/stores/pet'
import HomePet from '@/components/HomePet.vue'

const pet = usePet()
</script>

<style scoped>
.page-sub {
  margin: 8px 0 0;
  color: #8a8a84;
  font-size: 13px;
}
.pet-panel {
  border: 1px solid #eeeeeb;
  border-radius: 18px;
  background: #fff;
  overflow: hidden;
}
.pet-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 22px 24px;
  border-bottom: 1px solid #eeeeeb;
}
.toolbar-title { font-size: 15px; font-weight: 760; color: #242421; }
.toolbar-desc { margin-top: 4px; color: #777770; font-size: 13px; }
.pet-list { display: flex; flex-direction: column; }
.pet-row {
  display: flex;
  align-items: center;
  gap: 20px;
  min-height: 124px;
  padding: 18px 24px;
  border-bottom: 1px solid #eeeeeb;
  cursor: pointer;
  transition: background .14s;
}
.pet-row:last-child { border-bottom: 0; }
.pet-row:hover { background: #fafaf8; }
.pet-row.selected { background: #f6f6f3; }
.pet-preview {
  width: 92px;
  height: 86px;
  border: 1px solid #e7e7e4;
  border-radius: 16px;
  background: #fff;
  display: grid;
  place-items: end center;
  overflow: hidden;
  flex-shrink: 0;
}
.pet-preview :deep(.home-pet) {
  transform: translateY(0);
  animation: none;
}
.pet-copy { flex: 1; min-width: 0; }
.pet-name { font-size: 16px; font-weight: 760; color: #242421; }
.pet-desc { margin-top: 6px; color: #777770; font-size: 13px; }
.pet-select {
  border: 0;
  border-radius: 999px;
  background: #f1f1ef;
  color: #242421;
  min-height: 34px;
  padding: 0 16px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
.pet-row.selected .pet-select {
  color: #9a9a93;
  background: #eeeeeb;
}
</style>
