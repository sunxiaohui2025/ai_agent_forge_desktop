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
  padding: 18px 20px;
  border-bottom: 1px solid #eeeeeb;
}
.toolbar-title { font-size: 15px; font-weight: 760; color: #242421; }
.toolbar-desc { margin-top: 4px; color: #777770; font-size: 13px; }
.pet-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 12px;
}
.pet-row {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 86px;
  padding: 12px;
  border: 1px solid #eeeeeb;
  border-radius: 14px;
  background: #fff;
  cursor: pointer;
  transition: background .14s, border-color .14s, box-shadow .14s;
}
.pet-row:hover { background: #fafaf8; border-color: #e2e2de; }
.pet-row.selected {
  background: #f6f6f3;
  border-color: #d9d9d5;
  box-shadow: 0 10px 26px rgba(0,0,0,.04);
}
.pet-preview {
  width: 86px;
  height: 74px;
  border: 0;
  border-radius: 13px;
  background: #f7f7f5;
  display: grid;
  place-items: center;
  overflow: visible;
  flex-shrink: 0;
}
.pet-preview :deep(.home-pet) {
  animation: none;
}
.pet-copy { flex: 1; min-width: 0; }
.pet-name { font-size: 14px; font-weight: 760; color: #242421; }
.pet-desc {
  margin-top: 4px;
  color: #777770;
  font-size: 12px;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.pet-select {
  border: 0;
  border-radius: 999px;
  background: #f1f1ef;
  color: #242421;
  min-height: 28px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  flex-shrink: 0;
}
.pet-row.selected .pet-select {
  color: #9a9a93;
  background: #eeeeeb;
}
@media (max-width: 980px) {
  .pet-list { grid-template-columns: 1fr; }
}
</style>
