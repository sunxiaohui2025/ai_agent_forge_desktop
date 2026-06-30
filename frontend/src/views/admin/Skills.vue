<template>
  <div class="page">
    <div class="page-head">
      <div>
        <span class="page-title">技能</span>
        <span class="page-count">{{ filteredRows.length }}</span>
      </div>
      <div class="head-actions">
        <el-button type="primary" @click="openUpload"><el-icon><Upload /></el-icon>上传 Skill 包</el-button>
        <el-button  @click="openCreate"><el-icon><Plus /></el-icon>新建 Skill</el-button>
        <el-button @click="openMarket"><el-icon><Shop /></el-icon>从市场安装技能</el-button>
      </div>
    </div>
    <div class="plugin-toolbar">
      <el-input v-model="keyword" clearable placeholder="搜索技能..." />
    </div>
    <div class="plugin-grid">
      <article v-for="row in filteredRows" :key="row.id" class="plugin-card">
        <div class="plugin-top">
          <div class="slash">{{ fallbackInitial(row.name || row.code) }}</div>
          <div class="plugin-main">
            <div class="plugin-code">{{ row.code }}</div>
            <div class="plugin-name">{{ row.name || '未命名 Skill' }}</div>
          </div>
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '停用' }}</el-tag>
          <el-tag v-if="isBuiltin(row)" type="warning" size="small" effect="light" style="margin-left:6px">内置</el-tag>
        </div>
        <p class="plugin-desc">{{ row.description || row.user_summary || '暂无描述' }}</p>
        <div class="plugin-meta-row">
          <div class="meta-tags">
            <span class="meta-tag">{{ row.type }}</span>
            <span class="meta-tag">{{ skillSource(row) }}</span>
            <span class="meta-tag">v{{ row.version || 1 }}</span>
          </div>
          <div class="plugin-actions">
            <button v-if="row.source_json?.path" @click="openDetail(row)">详情</button>
            <button @click="openEdit(row)">编辑</button>
            <button @click="openSummary(row)">使用说明</button>
            <button v-if="!isBuiltin(row)" class="danger" @click="onDelete(row)">删除</button>
          </div>
        </div>
      </article>
      <button v-if="!filteredRows.length" class="empty-plugin" @click="openCreate">
        <span class="empty-icon">{{ keyword ? 'S' : '+' }}</span>
        <span class="empty-title">{{ keyword ? '没有找到匹配技能' : '还没有技能' }}</span>
        <span class="empty-desc">{{ keyword ? '换个关键词试试，或新建一个可复用技能。' : '把常用能力沉淀成技能，在对话里一键调用。' }}</span>
        <span class="empty-action">{{ keyword ? '新建技能' : '新建第一个技能' }}</span>
      </button>
    </div>

    <!-- Detail drawer with file tree + content viewer -->
    <el-drawer v-model="detailVisible" :size="900" direction="rtl" :title="detailTitle">
      <div class="detail-wrap">
        <div class="tree-pane">
          <div class="tree-head">{{ tree?.root }}</div>
          <el-tree
            v-if="tree"
            :data="tree.tree"
            :props="{ label: 'name', children: 'children' }"
            node-key="path"
            :default-expand-all="true"
            :expand-on-click-node="false"
            @node-click="onNodeClick"
          >
            <template #default="{ node, data }">
              <span class="tree-node">
                <el-icon v-if="data.type === 'dir'"><Folder /></el-icon>
                <el-icon v-else><Document /></el-icon>
                <span>{{ data.name }}</span>
                <span v-if="data.type === 'file'" class="muted file-size">{{ formatSize(data.size) }}</span>
              </span>
            </template>
          </el-tree>
        </div>
        <div class="content-pane">
          <div v-if="!currentFile" class="content-empty">点击左侧文件查看内容</div>
          <template v-else>
            <div class="content-head">
              <code>{{ currentFile.path }}</code>
              <span class="muted">{{ formatSize(currentFile.size) }}</span>
              <div class="head-actions">
                <template v-if="!editingFile">
                  <el-button v-if="currentFile.editable" size="small" type="primary" plain @click="startEdit">
                    <el-icon><EditPen /></el-icon>编辑
                  </el-button>
                  <el-tooltip v-else content="该文件类型不允许在线编辑" placement="top">
                    <el-button size="small" disabled>
                      <el-icon><Lock /></el-icon>只读
                    </el-button>
                  </el-tooltip>
                </template>
                <template v-else>
                  <el-button size="small" @click="cancelEdit">取消</el-button>
                  <el-button size="small" type="primary" :loading="saving" @click="saveEdit"
                             :disabled="editBuffer === currentFile.content">
                    <el-icon><Check /></el-icon>保存
                  </el-button>
                </template>
              </div>
            </div>
            <div v-if="editingFile" class="editor-wrap">
              <textarea
                ref="editorRef"
                v-model="editBuffer"
                class="editor-area"
                spellcheck="false"
                @keydown.tab.prevent="onTab"
                @keydown.ctrl.s.prevent="saveEdit"
                @keydown.meta.s.prevent="saveEdit"
              />
              <div class="editor-footer">
                <span class="muted">{{ editBuffer.length }} 字符 · {{ editBuffer.split('\n').length }} 行</span>
                <span class="muted">Ctrl/Cmd + S 保存</span>
              </div>
            </div>
            <div v-else class="code-viewer">
              <div class="line-numbers">
                <div v-for="n in lineCount" :key="n">{{ n }}</div>
              </div>
              <pre class="code">{{ currentFile.content }}</pre>
            </div>
          </template>
        </div>
      </div>
    </el-drawer>

    <!-- Manual create / edit dialog -->
    <el-dialog v-model="visible" :title="editing ? '编辑 Skill' : '新建 Skill'" width="720px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="编码"><el-input v-model="form.code" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="form.type">
            <el-radio value="atomic">原子</el-radio>
            <el-radio value="composite">组合 (YAML DAG)</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.type === 'atomic'" label="路径/调用">
          <el-input v-model="atomicPath" placeholder="path:/storage/skills/xxx 或 callable:pkg.mod:func" />
          <div style="font-size:12px;color:var(--m-text-secondary);margin-top:4px">
            前缀 <code>path:</code> 或 <code>callable:</code>。如要上传 zip 包,请用右上"上传 Skill 包"
          </div>
        </el-form-item>
        <el-form-item v-else label="YAML">
          <el-input v-model="yamlText" type="textarea" :rows="14" :placeholder="yamlSample" />
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>

    <!-- Upload Skill package dialog -->
    <el-dialog v-model="uploadVisible" title="上传 Skill 包" width="560px" destroy-on-close>
      <el-form :model="uploadForm" :rules="uploadRules" ref="uploadFormRef" label-width="100px">
        <el-form-item label="编码" prop="code">
          <el-input v-model="uploadForm.code" placeholder="英文小写,作为目录名,如 pdf_extract" />
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="uploadForm.name" placeholder="显示名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="uploadForm.description" type="textarea" :rows="2" placeholder="留空则从 SKILL.md 提取" />
        </el-form-item>
        <el-form-item label="Skill 包" prop="file">
          <el-upload
            ref="uploadRef"
            drag
            :auto-upload="false"
            :show-file-list="true"
            :limit="1"
            :on-change="onFileChange"
            :on-remove="onFileRemove"
            :on-exceed="onFileExceed"
            accept=".zip"
          >
            <el-icon class="el-icon--upload" :size="40"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽 zip 包到这里,或<em>点击选择</em></div>
            <template #tip>
              <div style="font-size:12px;color:var(--m-text-secondary);margin-top:8px">
                zip 包根目录(或唯一子目录)需包含 <code>SKILL.md</code>
              </div>
            </template>
          </el-upload>
        </el-form-item>

        <!-- Security findings: shown after a blocked attempt -->
        <el-form-item v-if="uploadFindings.length" label="安全扫描">
          <el-alert type="warning" :closable="false" show-icon
                   title="检测到潜在风险,请确认后继续">
            <template #default>
              <div class="findings-list">
                <div v-for="(f, i) in uploadFindings.slice(0, 8)" :key="i" class="finding">
                  <code class="finding-file">{{ f.file }}</code>
                  <span class="finding-rule">{{ f.rule }}</span>
                  <span class="finding-snippet">{{ f.snippet }}</span>
                </div>
                <div v-if="uploadFindings.length > 8" class="finding muted">
                  …还有 {{ uploadFindings.length - 8 }} 项
                </div>
              </div>
            </template>
          </el-alert>
          <el-checkbox v-model="uploadForm.force" style="margin-top:8px">
            我已确认上述内容,强制上传
          </el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="onUploadSubmit">上传</el-button>
      </template>
    </el-dialog>

    <!-- Usage summary editor: view + edit the AI-generated user_summary. -->
    <el-dialog v-model="summaryVisible" :title="`使用说明 · ${summaryRow?.name || ''}`" width="640px">
      <div v-if="summaryRow" class="summary-meta muted">
        <span>{{ summaryRow.code }}</span>
        <span v-if="summaryRow.user_summary_updated_at">· 更新于 {{ formatTime(summaryRow.user_summary_updated_at) }}</span>
      </div>
      <el-input
        v-model="summaryText"
        type="textarea"
        :rows="10"
        placeholder="说明这个 Skill 是做什么的、什么时候使用、给出 1-2 个调用示例。留空则恢复 AI 自动生成的说明。"
      />
      <template #footer>
        <el-button @click="summaryVisible = false">取消</el-button>
        <el-button @click="onResetSummary" :disabled="summarySaving">重置为自动生成</el-button>
        <el-button type="primary" :loading="summarySaving" @click="onSaveSummary">保存</el-button>
      </template>
    </el-dialog>

    <!-- SkillHub market drawer -->
    <el-drawer v-model="marketVisible" :size="980" direction="rtl" title="从市场安装技能" class="market-drawer">
      <div class="market-wrap">
        <div class="market-toolbar">
          <el-input
            v-model="marketQuery"
            clearable
            placeholder="搜索 SkillHub 技能..."
            @keyup.enter="onMarketSearch"
            @clear="onMarketSearch"
          >
            <template #append>
              <el-button @click="onMarketSearch"><el-icon><Search /></el-icon></el-button>
            </template>
          </el-input>
          <el-radio-group v-model="marketSection" :disabled="!!marketQuery.trim()" @change="reloadMarket">
            <el-radio-button v-for="s in SECTIONS" :key="s.key" :value="s.key">{{ s.label }}</el-radio-button>
          </el-radio-group>
        </div>

        <div v-loading="marketLoading" class="market-grid">
          <article
            v-for="item in marketItems"
            :key="item.slug"
            class="market-card"
            :class="{ active: marketDetail?.slug === item.slug }"
            @click="openMarketDetail(item)"
          >
            <div class="market-card-top">
              <img v-if="item.icon" :src="item.icon" class="market-icon" alt="" @error="onIconError" />
              <div v-else class="market-icon market-icon-fallback">{{ fallbackInitial(item.name) }}</div>
              <div class="market-card-main">
                <div class="market-name">{{ item.name }}</div>
                <div class="market-owner muted">{{ item.owner || item.source }}</div>
              </div>
              <el-tag v-if="item.installed" type="info" size="small">已安装</el-tag>
            </div>
            <p class="market-desc">{{ item.description || '暂无描述' }}</p>
            <div class="market-meta">
              <span class="market-stat"><el-icon><Download /></el-icon>{{ formatCount(item.downloads) }}</span>
              <span class="market-stat"><el-icon><Star /></el-icon>{{ formatCount(item.stars) }}</span>
              <span v-if="item.version" class="market-stat">v{{ item.version }}</span>
              <el-button
                size="small"
                :type="item.installed ? 'default' : 'primary'"
                :loading="installingSlug === item.slug"
                @click.stop="onInstall(item)"
              >{{ item.installed ? '重新安装' : '安装' }}</el-button>
            </div>
          </article>
          <div v-if="!marketLoading && !marketItems.length" class="market-empty">
            {{ marketQuery.trim() ? '没有找到匹配的技能' : '暂无数据' }}
          </div>
        </div>

        <div v-if="marketItems.length" class="market-pager">
          <el-button :disabled="marketPage <= 1 || marketLoading" @click="goPage(marketPage - 1)">上一页</el-button>
          <span class="muted">第 {{ marketPage }} 页</span>
          <el-button :disabled="!marketHasMore || marketLoading" @click="goPage(marketPage + 1)">下一页</el-button>
        </div>
      </div>
    </el-drawer>

    <!-- Market install confirm (detail + security reports + findings) -->
    <el-dialog v-model="installVisible" :title="`安装 · ${installTarget?.name || ''}`" width="600px" destroy-on-close>
      <div v-if="installTarget" class="install-body">
        <p class="market-desc">{{ installTarget.description }}</p>
        <div class="install-meta muted">
          <span>{{ installTarget.owner || installTarget.source }}</span>
          <span v-if="detailLoaded?.version">· v{{ detailLoaded.version }}</span>
          <span>· 本地编码 {{ slugToCode(installTarget.slug) }}</span>
        </div>

        <div v-if="detailLoaded?.security_reports?.length" class="security-reports">
          <div class="install-label">SkillHub 安全报告</div>
          <a
            v-for="r in detailLoaded.security_reports"
            :key="r.vendor"
            :href="r.report_url"
            target="_blank"
            rel="noopener"
            class="security-item"
          >
            <el-tag :type="r.status === 'benign' ? 'success' : 'warning'" size="small">{{ r.vendor }}</el-tag>
            <span>{{ r.status_text || r.status }}</span>
          </a>
        </div>

        <el-alert v-if="installTarget.installed" type="warning" :closable="false" show-icon
                  title="该技能已安装，继续将覆盖本地版本（旧目录会先备份）" style="margin-top:10px" />

        <!-- local security scan findings (after a blocked install) -->
        <div v-if="installFindings.length" class="install-findings">
          <el-alert type="warning" :closable="false" show-icon title="本地安全扫描检测到潜在风险">
            <div class="findings-list">
              <div v-for="(f, i) in installFindings.slice(0, 8)" :key="i" class="finding">
                <code class="finding-file">{{ f.file }}</code>
                <span class="finding-rule">{{ f.rule }}</span>
                <span class="finding-snippet">{{ f.snippet }}</span>
              </div>
              <div v-if="installFindings.length > 8" class="finding muted">…还有 {{ installFindings.length - 8 }} 项</div>
            </div>
          </el-alert>
          <el-checkbox v-model="installForce" style="margin-top:8px">我已确认上述内容，强制安装</el-checkbox>
        </div>
      </div>
      <template #footer>
        <el-button @click="installVisible = false">取消</el-button>
        <el-button type="primary" :loading="installingSlug === installTarget?.slug" @click="confirmInstall">
          {{ installTarget?.installed ? '覆盖安装' : '安装' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted, reactive, computed, nextTick } from 'vue'
import { ElMessage, ElMessageBox, genFileId } from 'element-plus'
import type { UploadInstance, UploadRawFile } from 'element-plus'
import { api } from '@/api'

const yamlSample = `name: contract_review_flow
description: 合同审查流程
steps:
  - id: extract
    skill: pdf_extract
    input:
      file: "{{trigger.file}}"
  - id: analyze
    skill: llm_call
    depends_on: [extract]
    input:
      text: "{{extract.value}}"
`

const rows = ref<any[]>([])
const keyword = ref('')
const visible = ref(false)
const editing = ref<any | null>(null)
const form = reactive<any>({ code: '', name: '', description: '', type: 'atomic', source_json: {}, enabled: true })
const atomicPath = ref('')
const yamlText = ref('')

// upload state
const uploadVisible = ref(false)
const uploadFormRef = ref<any>(null)
const uploadRef = ref<UploadInstance>()
const uploadForm = reactive<any>({ code: '', name: '', description: '', file: null as File | null, force: false })
const uploading = ref(false)
const uploadFindings = ref<any[]>([])
const uploadRules = {
  code: [
    { required: true, message: '请输入编码', trigger: 'blur' },
    { pattern: /^[a-z][a-z0-9_-]{1,63}$/, message: '小写字母开头,允许 a-z 0-9 _ -', trigger: 'blur' },
  ],
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  file: [{ required: true, message: '请选择 zip 包', trigger: 'change' }],
}

async function load() { rows.value = await api.skills() }
onMounted(load)

const filteredRows = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((row) => [
    row.code, row.name, row.description, row.user_summary, row.type, skillSource(row),
  ].some((v) => String(v || '').toLowerCase().includes(q)))
})

function skillSource(row: any) {
  if (row.source_json?.path) return '已上传'
  if (row.source_json?.callable) return 'callable'
  if (row.source_json?.yaml) return 'YAML'
  return 'manual'
}

// Built-in callable skills (e.g. 专家生成器/create_expert) are seeded by the
// backend and must not be deleted from the UI.
function isBuiltin(row: any) {
  return row?.source_json?.builtin === true
}

function fallbackInitial(value: string) {
  const s = String(value || '').trim()
  return (Array.from(s)[0] || 'S').toUpperCase()
}

function openCreate() {
  editing.value = null
  Object.assign(form, { code: '', name: '', description: '', type: 'atomic', source_json: {}, enabled: true })
  atomicPath.value = ''; yamlText.value = ''
  visible.value = true
}
function openEdit(row: any) {
  editing.value = row
  Object.assign(form, JSON.parse(JSON.stringify(row)))
  if (row.type === 'atomic') {
    atomicPath.value = row.source_json.path ? `path:${row.source_json.path}` :
                       row.source_json.callable ? `callable:${row.source_json.callable}` : ''
  } else {
    yamlText.value = row.source_json.yaml || ''
  }
  visible.value = true
}
async function onSubmit() {
  if (form.type === 'atomic') {
    const v = atomicPath.value.trim()
    if (v.startsWith('path:')) form.source_json = { path: v.slice(5).trim() }
    else if (v.startsWith('callable:')) form.source_json = { callable: v.slice(9).trim() }
    else { ElMessage.error('请填写 path: 或 callable:'); return }
  } else {
    form.source_json = { yaml: yamlText.value }
  }
  if (editing.value) await api.updateSkill(editing.value.id, form)
  else await api.createSkill(form)
  visible.value = false
  ElMessage.success('保存成功')
  await load()
}
async function onDelete(row: any) {
  try { await ElMessageBox.confirm(`删除 ${row.code}?`, '确认', { type: 'warning' }); await api.deleteSkill(row.id); await load() } catch {}
}

// ---------- usage summary editor ----------
const summaryVisible = ref(false)
const summaryRow = ref<any>(null)
const summaryText = ref('')
const summarySaving = ref(false)

function openSummary(row: any) {
  summaryRow.value = row
  summaryText.value = row.user_summary || ''
  summaryVisible.value = true
}
function formatTime(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', { hour12: false })
}
async function onSaveSummary() {
  if (!summaryRow.value) return
  summarySaving.value = true
  try {
    const r = summaryRow.value
    await api.updateSkill(r.id, {
      code: r.code,
      name: r.name,
      description: r.description || '',
      type: r.type,
      source_json: r.source_json || {},
      enabled: r.enabled,
      user_summary: (summaryText.value || '').trim(),
    })
    ElMessage.success('已保存')
    summaryVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    summarySaving.value = false
  }
}
async function onResetSummary() {
  if (!summaryRow.value) return
  try {
    await ElMessageBox.confirm('重置后将清空当前说明，并触发 AI 重新生成。继续？', '确认', { type: 'warning' })
  } catch { return }
  summarySaving.value = true
  try {
    const r = summaryRow.value
    // empty user_summary signals "let backend re-summarize"
    await api.updateSkill(r.id, {
      code: r.code, name: r.name, description: r.description || '',
      type: r.type, source_json: r.source_json || {}, enabled: r.enabled,
      user_summary: null,
    })
    await api.resummarizeSkill(r.id)
    ElMessage.success('已重置，稍后刷新列表查看')
    summaryVisible.value = false
    setTimeout(() => { load() }, 4000)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '重置失败')
  } finally {
    summarySaving.value = false
  }
}

// ---------- detail drawer ----------
const detailVisible = ref(false)
const detailRow = ref<any>(null)
const tree = ref<any>(null)
const currentFile = ref<any>(null)
const editingFile = ref(false)
const editBuffer = ref('')
const saving = ref(false)
const editorRef = ref<HTMLTextAreaElement | null>(null)
const detailTitle = computed(() => detailRow.value ? `${detailRow.value.name} · 详情` : '详情')
const lineCount = computed(() => {
  if (!currentFile.value?.content) return 0
  return Math.max(1, currentFile.value.content.split('\n').length)
})

async function openDetail(row: any) {
  detailRow.value = row
  detailVisible.value = true
  currentFile.value = null
  editingFile.value = false
  try {
    tree.value = await api.skillFiles(row.id)
    const skillMd = (tree.value.tree || []).find((n: any) => n.type === 'file' && n.name.toLowerCase() === 'skill.md')
    if (skillMd) await loadFile(skillMd.path)
  } catch {}
}

async function onNodeClick(data: any) {
  if (data.type === 'file') await loadFile(data.path)
}
async function loadFile(path: string) {
  if (!detailRow.value) return
  if (editingFile.value && editBuffer.value !== currentFile.value?.content) {
    try {
      await ElMessageBox.confirm('当前文件未保存,切换会丢失修改,继续?', '确认', { type: 'warning' })
    } catch { return }
  }
  editingFile.value = false
  try { currentFile.value = await api.skillFile(detailRow.value.id, path) } catch {}
}

function startEdit() {
  if (!currentFile.value?.editable) return
  editBuffer.value = currentFile.value.content || ''
  editingFile.value = true
  nextTick().then(() => editorRef.value?.focus())
}

function cancelEdit() {
  if (editBuffer.value !== currentFile.value?.content) {
    if (!confirm('放弃本次修改?')) return
  }
  editingFile.value = false
}

function onTab(e: KeyboardEvent) {
  const ta = editorRef.value
  if (!ta) return
  const start = ta.selectionStart
  const end = ta.selectionEnd
  editBuffer.value = editBuffer.value.slice(0, start) + '  ' + editBuffer.value.slice(end)
  nextTick().then(() => {
    if (editorRef.value) editorRef.value.selectionStart = editorRef.value.selectionEnd = start + 2
  })
}

async function saveEdit() {
  if (!currentFile.value || !detailRow.value) return
  if (editBuffer.value === currentFile.value.content) return
  saving.value = true
  try {
    await api.saveSkillFile(detailRow.value.id, currentFile.value.path, editBuffer.value)
    ElMessage.success('保存成功')
    currentFile.value = await api.skillFile(detailRow.value.id, currentFile.value.path)
    editingFile.value = false
    await load()
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    if (detail && typeof detail === 'object' && detail.findings) {
      ElMessage.error(`内容触发安全规则: ${detail.findings.map((f: any) => f.rule).join(', ')}`)
    }
  } finally {
    saving.value = false
  }
}
function formatSize(b: number) {
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b/1024).toFixed(1)} KB`
  return `${(b/1024/1024).toFixed(2)} MB`
}

function openUpload() {
  Object.assign(uploadForm, { code: '', name: '', description: '', file: null, force: false })
  uploadFindings.value = []
  uploadVisible.value = true
}
function onFileChange(uf: any) {
  uploadForm.file = uf.raw as File
  // a fresh file should reset prior findings/force decisions
  uploadFindings.value = []
  uploadForm.force = false
}
function onFileRemove() {
  uploadForm.file = null
  uploadFindings.value = []
  uploadForm.force = false
}
function onFileExceed(files: File[]) {
  // limit=1: dragging a new zip should REPLACE the previous one. Without this,
  // el-upload rejects the extra file and keeps showing the old name. Clear the
  // internal list, then start the new file so the UI + form stay in sync.
  uploadRef.value?.clearFiles()
  const file = files[0] as UploadRawFile
  file.uid = genFileId()
  uploadRef.value?.handleStart(file)
  uploadForm.file = file
  uploadFindings.value = []
  uploadForm.force = false
}
async function onUploadSubmit() {
  const ok = await uploadFormRef.value?.validate().catch(() => false)
  if (!ok) return
  if (!uploadForm.file) { ElMessage.error('请选择 zip 包'); return }
  uploading.value = true
  try {
    await api.uploadSkill(
      uploadForm.file, uploadForm.code, uploadForm.name, uploadForm.description, uploadForm.force,
    )
    ElMessage.success('上传成功')
    uploadVisible.value = false
    await load()
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    if (detail && typeof detail === 'object' && Array.isArray(detail.findings)) {
      // security scan blocked — surface findings inline so admin can review and tick force
      uploadFindings.value = detail.findings
      ElMessage.warning(detail.message || '检测到潜在风险,请确认后强制上传')
    } else if (typeof detail === 'string') {
      ElMessage.error(detail)
    } else if (detail && typeof detail === 'object') {
      const head = detail.message || '上传失败'
      const hint = detail.hint ? ` (${detail.hint})` : ''
      ElMessage.error(`${head}${hint}`)
      console.error('upload skill blocked:', detail)
    } else {
      ElMessage.error('上传失败')
    }
  } finally {
    uploading.value = false
  }
}

// ---------- SkillHub market ----------
const SECTIONS = [
  { key: 'hot', label: '热门' },
  { key: 'featured', label: '精选' },
  { key: 'newest', label: '最新' },
  { key: 'recommended', label: '推荐' },
  { key: 'trending', label: '趋势' },
]
const marketVisible = ref(false)
const marketLoading = ref(false)
const marketQuery = ref('')
const marketSection = ref('hot')
const marketItems = ref<any[]>([])
const marketPage = ref(1)
const marketHasMore = ref(false)
const marketDetail = ref<any>(null)

const installVisible = ref(false)
const installTarget = ref<any>(null)
const detailLoaded = ref<any>(null)
const installFindings = ref<any[]>([])
const installForce = ref(false)
const installingSlug = ref<string | null>(null)

function slugToCode(slug: string) {
  let code = String(slug || '').toLowerCase().replace(/[^a-z0-9_-]/g, '-').replace(/^-+|-+$/g, '')
  if (!/^[a-z]/.test(code)) code = `skill-${code}`
  return code.slice(0, 64)
}
function formatCount(n: number) {
  if (!n) return '0'
  if (n >= 10000) return `${(n / 10000).toFixed(1)}w`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}
function onIconError(e: Event) {
  (e.target as HTMLImageElement).style.visibility = 'hidden'
}

function openMarket() {
  marketVisible.value = true
  marketQuery.value = ''
  marketSection.value = 'hot'
  marketPage.value = 1
  marketDetail.value = null
  reloadMarket()
}
async function reloadMarket() {
  marketLoading.value = true
  try {
    const res = await api.marketSkills({
      q: marketQuery.value.trim(),
      section: marketSection.value,
      page: marketPage.value,
      page_size: 24,
    })
    marketItems.value = res.items || []
    marketHasMore.value = !!res.has_more
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载市场失败')
    marketItems.value = []
  } finally {
    marketLoading.value = false
  }
}
function onMarketSearch() {
  marketPage.value = 1
  reloadMarket()
}
function goPage(p: number) {
  if (p < 1) return
  marketPage.value = p
  reloadMarket()
}
async function openMarketDetail(item: any) {
  marketDetail.value = item
  openInstall(item)
}
function openInstall(item: any) {
  installTarget.value = item
  installFindings.value = []
  installForce.value = false
  detailLoaded.value = null
  installVisible.value = true
  // fetch detail (version + security reports) in the background
  api.marketSkillDetail(item.slug).then((d) => { detailLoaded.value = d }).catch(() => {})
}
function onInstall(item: any) {
  openInstall(item)
}
async function confirmInstall() {
  const item = installTarget.value
  if (!item) return
  installingSlug.value = item.slug
  try {
    await api.installMarketSkill(item.slug, {
      name: item.name,
      description: item.description || '',
      force: installForce.value,
      overwrite: !!item.installed,
    })
    ElMessage.success('安装成功')
    installVisible.value = false
    // reflect installed state in the market list + refresh main library
    item.installed = true
    await load()
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    if (detail && typeof detail === 'object' && Array.isArray(detail.findings)) {
      installFindings.value = detail.findings
      ElMessage.warning(detail.message || '检测到潜在风险，请确认后强制安装')
    } else if (typeof detail === 'string') {
      ElMessage.error(detail)
    } else if (detail && typeof detail === 'object') {
      ElMessage.error(detail.message || '安装失败')
    } else {
      ElMessage.error('安装失败')
    }
  } finally {
    installingSlug.value = null
  }
}
</script>

<style scoped>
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-head > div:first-child { display: flex; align-items: baseline; gap: 10px; }
.page-count { color: #8a8a84; font-size: 13px; font-weight: 650; }
.head-actions { display: flex; gap: 8px; }
.plugin-toolbar {
  max-width: 420px;
  margin: -10px 0 18px;
}
.plugin-toolbar :deep(.el-input__wrapper) {
  border-radius: 999px;
  box-shadow: none;
  background: #f5f5f2;
  padding: 0 14px;
}
.plugin-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.plugin-card {
  min-height: 184px;
  padding: 18px;
  border: 1px solid #eeeeeb;
  border-radius: 18px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.plugin-card:hover { border-color: #d8d8d4; }
.plugin-top { display: flex; align-items: center; gap: 12px; min-width: 0; }
.slash {
  width: 42px; height: 42px; border-radius: 12px;
  background: #f2f2ef; color: #56554e;
  display: flex; align-items: center; justify-content: center;
  font-size: 17px; font-weight: 760;
  flex-shrink: 0;
}
.plugin-main { flex: 1; min-width: 0; }
.plugin-code { font-size: 15px; font-weight: 760; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plugin-name { margin-top: 3px; color: #8a8a84; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plugin-desc {
  margin: 0;
  color: #777770;
  font-size: 13px;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.plugin-meta-row {
  display: flex; align-items: center;
  justify-content: space-between;
  margin-top: auto;
}
.meta-tags { display: flex; align-items: center; gap: 6px; }
.meta-tag {
  padding: 4px 8px; border-radius: 999px;
  background: #f6f6f3; color: #777770;
  font-size: 12px;
}
.plugin-actions {
  display: flex; gap: 4px;
  opacity: 0; transition: opacity .15s;
}
.plugin-card:hover .plugin-actions { opacity: 1; }
.plugin-actions button {
  border: 0; background: #f1f1ef; color: #30302d;
  border-radius: 999px; min-height: 30px; padding: 0 12px;
  cursor: pointer; font-size: 12px; font-weight: 650;
}
.plugin-actions button:hover { background: #e5e5e2; }
.plugin-actions .danger { color: #b5392f; background: #f8ebe9; }
.plugin-actions .danger:hover { background: #f2dcd9; }
.empty-plugin {
  border: 1px dashed #e6e6e2;
  background: #fafaf8; color: #56554e;
  border-radius: 16px; padding: 16px;
  cursor: pointer; font-size: 12px; font-weight: 650;
  min-height: 126px;
  width: min(360px, 100%);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  text-align: left;
  gap: 5px;
}
.empty-plugin:hover {
  background: #f6f6f3;
  border-color: #ddddda;
}
.empty-icon {
  width: 30px;
  height: 30px;
  border-radius: 10px;
  background: #eeeeeb;
  color: #777770;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 760;
  margin-bottom: 3px;
}
.empty-title { font-size: 13px; font-weight: 760; color: #3f3f3b; }
.empty-desc { font-size: 12px; color: #8a8a84; line-height: 1.45; max-width: 280px; }
.empty-action { margin-top: 4px; font-size: 12px; font-weight: 700; color: #56554e; }
.summary-meta {
  font-size: 12px; margin-bottom: 8px;
  display: flex; align-items: center; gap: 8px;
}
.summary-cell {
  font-size: 12px;
  line-height: 1.5;
  color: var(--m-text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.muted { color: var(--m-text-tertiary); font-size: 12px; }
.detail-wrap { display: flex; height: calc(100vh - 80px); }
.tree-pane {
  width: 280px; flex-shrink: 0;
  border-right: 1px solid var(--m-border);
  overflow: auto; padding: 8px 0;
  background: var(--m-bg-soft);
}
.tree-head {
  padding: 8px 16px; font-size: 12px; font-weight: 600;
  color: var(--m-text-secondary); text-transform: uppercase; letter-spacing: .06em;
}
.tree-node { display: flex; align-items: center; gap: 6px; }
.file-size { font-size: 11px; margin-left: auto; padding-left: 8px; }

.content-pane { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.content-empty {
  flex: 1; display: flex; align-items: center; justify-content: center;
  color: var(--m-text-tertiary);
}
.content-head {
  padding: 12px 16px;
  display: flex; align-items: center; gap: 12px;
  background: var(--m-bg-soft);
  border-bottom: 1px solid var(--m-border);
  font-size: 13px;
}
.content-head .head-actions { margin-left: auto; display: flex; gap: 6px; }
.code-viewer {
  flex: 1; overflow: auto; display: flex;
  background: #fafbfc;
  font-family: 'Roboto Mono', ui-monospace, Menlo, monospace;
  font-size: 13px; line-height: 1.65;
}
.line-numbers {
  text-align: right; padding: 16px 12px 16px 16px;
  color: var(--m-text-tertiary); user-select: none;
  border-right: 1px solid var(--m-border);
  background: var(--m-surface);
}
.code {
  flex: 1; margin: 0; padding: 16px;
  white-space: pre; overflow: auto;
  color: var(--m-text);
}

/* in-place editor */
.editor-wrap {
  flex: 1; display: flex; flex-direction: column; min-height: 0;
  background: var(--m-surface);
}
.editor-area {
  flex: 1; min-height: 0; resize: none;
  border: none; outline: none; padding: 16px;
  font-family: 'Roboto Mono', ui-monospace, Menlo, monospace;
  font-size: 13px; line-height: 1.65;
  color: var(--m-text); background: #fafbfc;
  white-space: pre; overflow: auto;
  tab-size: 2;
}
.editor-area:focus { background: #fff; box-shadow: inset 2px 0 0 var(--m-primary); }
.editor-footer {
  display: flex; justify-content: space-between;
  padding: 8px 16px;
  font-size: 11px; color: var(--m-text-secondary);
  background: var(--m-bg-soft);
  border-top: 1px solid var(--m-border);
}

.findings-list { max-height: 200px; overflow: auto; font-size: 12px; }
.finding {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 0;
  border-bottom: 1px dashed var(--m-border);
}
.finding:last-child { border-bottom: none; }
.finding.muted { color: var(--m-text-tertiary); justify-content: center; }
.finding-file {
  font-family: 'Roboto Mono', monospace;
  background: var(--m-surface-variant);
  padding: 1px 6px; border-radius: 4px;
  max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  flex-shrink: 0;
}
.finding-rule {
  font-weight: 600; color: var(--m-danger, #d33);
  flex-shrink: 0;
}
.finding-snippet {
  color: var(--m-text-secondary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  flex: 1; min-width: 0;
}

/* Action column buttons: Element Plus injects margin-left:12px between sibling
   buttons globally. Compress it to a tight gap here only. */
.row-actions { display: inline-flex; align-items: center; gap: 4px; }
.row-actions :deep(.el-button + .el-button) { margin-left: 0; }
.row-actions :deep(.el-button) { padding: 4px 6px; }
@media (max-width: 900px) { .plugin-grid { grid-template-columns: 1fr; } }

/* ---- SkillHub market ---- */
.market-wrap { display: flex; flex-direction: column; height: calc(100vh - 80px); }
.market-toolbar {
  display: flex; align-items: center; gap: 12px;
  padding-bottom: 14px; flex-wrap: wrap;
}
.market-toolbar .el-input { max-width: 360px; }
.market-grid {
  flex: 1; overflow: auto; min-height: 0;
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px;
  align-content: start; padding-right: 4px;
}
.market-card {
  border: 1px solid #eeeeeb; border-radius: 16px; background: #fff;
  padding: 14px; display: flex; flex-direction: column; gap: 10px;
  cursor: pointer; transition: border-color .15s, box-shadow .15s;
}
.market-card:hover { border-color: #d8d8d4; box-shadow: 0 2px 10px rgba(0,0,0,.04); }
.market-card.active { border-color: var(--m-primary, #4a6cf7); }
.market-card-top { display: flex; align-items: center; gap: 10px; min-width: 0; }
.market-icon {
  width: 38px; height: 38px; border-radius: 10px; object-fit: cover;
  background: #f2f2ef; flex-shrink: 0;
}
.market-icon-fallback {
  display: flex; align-items: center; justify-content: center;
  color: #56554e; font-weight: 760; font-size: 16px;
}
.market-card-main { flex: 1; min-width: 0; }
.market-name { font-size: 14px; font-weight: 720; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.market-owner { margin-top: 2px; }
.market-desc {
  margin: 0; color: #777770; font-size: 12px; line-height: 1.55;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.market-meta {
  display: flex; align-items: center; gap: 12px; margin-top: auto;
  font-size: 12px; color: #8a8a84;
}
.market-stat { display: inline-flex; align-items: center; gap: 3px; }
.market-meta .el-button { margin-left: auto; }
.market-empty {
  grid-column: 1 / -1; text-align: center; color: var(--m-text-tertiary);
  padding: 48px 0; font-size: 13px;
}
.market-pager {
  display: flex; align-items: center; justify-content: center; gap: 14px;
  padding-top: 12px;
}
.install-body { font-size: 13px; }
.install-meta { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.install-label { font-size: 12px; font-weight: 700; color: #56554e; margin: 10px 0 6px; }
.security-reports { display: flex; flex-direction: column; gap: 6px; }
.security-item { display: flex; align-items: center; gap: 8px; color: var(--m-text-secondary); text-decoration: none; }
.security-item:hover { text-decoration: underline; }
.install-findings { margin-top: 12px; }
@media (max-width: 900px) { .market-grid { grid-template-columns: 1fr; } }
</style>
