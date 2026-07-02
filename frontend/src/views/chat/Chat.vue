<template>
  <div class="chat-wrap" :class="{ 'split-mode': previewFile, 'home-mode': isHome }">
    <!-- Conversation -->
    <section class="conv">
      <div ref="scrollRef" class="messages">
        <div v-if="!chat.currentConvId || chat.messages.length === 0" class="welcome">
          <!-- <div class="welcome-mark">
            <span class="dot dot-1" /><span class="dot dot-2" />
            <span class="dot dot-3" /><span class="dot dot-4" />
          </div> -->
          <h2>
            <span>{{ homeTitle }}</span>
            
          </h2>
          <p v-if="!chat.currentAgent">暂无可用专家,请联系管理员授权</p>
        </div>

        <template v-else>
          <div
            v-for="m in chat.messages"
            v-show="!(m.role === 'user' && m.content_json?.hidden)"
            :key="m.id || m._tmp"
            :class="['msg', m.role, { 'is-highlighted': highlightedMessageId === m.id }]"
            :data-mid="m.id"
          >
            <div v-if="m.role === 'assistant'" :class="['avatar', 'bot', { 'is-thinking': isWaiting(m) }]">
              <span class="dot dot-1" /><span class="dot dot-2" />
              <span class="dot dot-3" /><span class="dot dot-4" />
            </div>
            <div class="bubble-stack">
              <!-- waiting indicator: shown only until first content arrives -->
              <div v-if="isWaiting(m)" class="thinking-pill">
                <span class="thinking-text">{{ thinkingLabel(m) }}</span>
                <span class="thinking-dots"><span /><span /><span /></span>
              </div>

              <!-- meta: 当前回答用的 agent / model. Only after the first token has arrived. -->
              <div v-if="m.role === 'assistant' && m._meta && m.content_json?.text" class="msg-meta">
                <span>{{ m._meta.agent_name }}</span>
                <span class="dot-sep">·</span>
                <!-- <code>{{ m._meta.model_id }}</code> -->
                <button
                  v-if="chat.currentAgent"
                  class="cap-info-btn cap-info-btn-sm"
                  :title="'查看专家能力'"
                  @click="openCapabilities(chat.currentAgent.id)"
                >
                  <el-icon :size="13"><InfoFilled /></el-icon>
                </button>
              </div>

              <!-- thinking block -->
              <details v-if="m.content_json?.thinking || m._thinking" class="thinking-card" :open="m._thinkingOpen ?? !m.content_json?.text">
                <summary>
                  <el-icon><Cpu /></el-icon>
                  <span>思考过程</span>
                  <span class="muted" style="font-size:11px;margin-left:6px">{{ (m.content_json?.thinking || m._thinking || '').length }} 字</span>
                </summary>
                <div class="thinking-body">
                  <div
                    :ref="(el) => setThinkingRef(el, m)"
                    class="thinking-content"
                  >{{ m.content_json?.thinking || m._thinking }}</div>
                </div>
              </details>

              <!-- tool / mcp / skill execution process -->
              <div v-if="m._steps?.length || m.tool_calls_json?.trace?.length" class="proc">
                <button class="proc-head" @click="toggleSteps(m)">
                  <el-icon v-if="stepsRunning(m)" class="is-loading proc-spin"><Loading /></el-icon>
                  <el-icon v-else class="proc-ok"><CircleCheckFilled /></el-icon>
                  <span class="proc-title">{{ stepsRunning(m) ? '执行中…' : '执行过程' }}</span>
                  <span class="proc-count">{{ stepCount(m) }} 个步骤</span>
                  <el-icon class="proc-caret" :class="{ open: isStepsOpen(m) }"><ArrowRight /></el-icon>
                </button>
                <div v-if="!isStepsOpen(m) && latestStep(m)" class="proc-live" :class="{ running: stepsRunning(m) }">
                  <span class="proc-live-dot" />
                  <span class="proc-live-text">{{ latestStepText(m) }}</span>
                </div>
                <div v-show="isStepsOpen(m)" class="step-list">
                  <template v-for="(s, i) in (m._steps || normalizeTrace(m.tool_calls_json?.trace))" :key="i">
                    <PackProgressCard
                      v-if="s.name?.startsWith('run_pack__')"
                      :pack-code="s.name.replace('run_pack__', '')"
                      :input="s.input"
                      :output="s.output"
                    />
                    <details v-else :class="['step-card', s.status]">
                      <summary class="step-head">
                        <el-icon v-if="s.status === 'running'" class="is-loading"><Loading /></el-icon>
                        <el-icon v-else-if="s.status === 'done'" style="color:var(--m-success)"><CircleCheckFilled /></el-icon>
                        <el-icon v-else><Tools /></el-icon>
                        <span class="step-name">{{ s.label || s.name }}</span>
                        <code v-if="s.summary" class="step-summary" :title="s.summary">{{ s.summary }}</code>
                        <span v-if="s.serverName" class="step-server">{{ s.serverName }}</span>
                        <span v-if="s.duration_ms" class="muted step-dur">{{ s.duration_ms }}ms</span>
                        <span v-if="s.input || s.output || s.name" class="step-io-toggle">
                          <svg class="step-chevron" viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 6 8 10 12 6"/></svg>
                        </span>
                      </summary>
                      <div class="step-body">
                        <div class="step-block step-id-row">
                          <span class="step-label">工具 ID</span>
                          <code class="step-raw-name">{{ s.name }}</code>
                        </div>
                        <div v-if="s.input" class="step-block"><div class="step-label">Input</div><pre>{{ formatStepData(s.input) }}</pre></div>
                        <div v-if="s.output" class="step-block"><div class="step-label">Output</div><pre>{{ formatStepData(s.output) }}</pre></div>
                      </div>
                    </details>
                  </template>
                </div>
              </div>

              <!-- UI Schema surfaces (interactive components) -->
              <div v-if="(m.content_json?.uis?.length) || m._uis?.length" class="ui-block">
                <MessageDispatcher
                  v-for="(s, ui) in (m._uis?.length ? m._uis : m.content_json.uis)"
                  :key="s.surface_id || ui"
                  :schema="s"
                  :on-agent-call="onAgentCall"
                />
              </div>

              <!-- permission approval history (resolved requests only; pending
                   ones surface in the floating panel above the messages) -->
              <div v-if="m._perms?.some((r: any) => r.status !== 'pending')" class="perm-block">
                <template v-for="(req, pi) in m._perms" :key="req.request_id || pi">
                  <div
                    v-if="req.status !== 'pending'"
                    :class="['perm-card', 'resolved', { collapsed: req._collapsed }]"
                  >
                    <div
                      class="perm-head clickable"
                      @click="req._collapsed = !req._collapsed"
                    >
                      <el-icon class="perm-icon">
                        <component :is="permStatusIcon(req)" />
                      </el-icon>
                      <span class="perm-title">{{ permHeadText(req) }}</span>
                      <span class="perm-tool">{{ req.tool_name }}</span>
                      <el-icon class="perm-caret">
                        <ArrowDown v-if="req._collapsed" /><ArrowUp v-else />
                      </el-icon>
                    </div>
                    <div v-show="!req._collapsed" class="perm-body">
                      <div class="perm-reason">{{ req.reason }}</div>
                      <pre v-if="req.summary" class="perm-summary">{{ req.summary }}</pre>
                    </div>
                  </div>
                </template>
              </div>

              <!-- main answer -->
              <div v-if="m.content_json?.text || m.role === 'user'" :class="['bubble', { 'bubble--clamped': m.role === 'user' && isLongUserMsg(m) && !expandedMsgs[getMsgKey(m)] }]">
                <template v-if="m.role === 'user'">
                  <div v-if="m.content_json?.files?.length" class="msg-files">
                    <span
                      v-for="(f, fi) in m.content_json.files"
                      :key="fi"
                      :class="['msg-file-chip', { clickable: canPreview(f) }]"
                      @click="canPreview(f) && openPreview(f)"
                    >
                      <el-icon :size="12"><Paperclip /></el-icon>
                      {{ f.name }}<span v-if="f.parsed_chars" class="msg-file-meta"> · {{ f.parsed_chars }}字</span>
                    </span>
                  </div>
                  <div class="bubble-content" v-html="md.render(m.content_json?.text || '')" @click="onRenderedContentClick"></div>
                  <div v-if="isLongUserMsg(m) && !expandedMsgs[getMsgKey(m)]" class="bubble-clamp-fade" />
                </template>
                <template v-else>
                  <template v-for="(seg, si) in parseSegments(m)" :key="seg.type === 'widget' ? (seg.partialKey || seg.stableKey) : `t-${si}`">
                    <div v-if="seg.type === 'text'" class="bubble-content" v-html="md.render(seg.content)" @click="onRenderedContentClick"></div>
                    <WidgetRenderer
                      v-else
                      :widget-code="seg.widgetCode"
                      :title="seg.title"
                      :is-streaming="seg.isStreaming"
                      @send-message="onWidgetSendMessage"
                    />
                  </template>
                </template>
              </div>

              <!-- file cards (saved outputs) — rendered after the answer text so
                   generated artifacts land at the bottom of the message and stay
                   visible without scrolling back up -->
              <div v-if="(m.content_json?.files?.length) || m._files?.length" class="files-block">
                <FileCard
                  v-for="(f, fi) in (m._files?.length ? m._files : m.content_json.files)"
                  :key="fi + (f.name || '')"
                  :file="f"
                  @preview="openPreview"
                />
              </div>

              <div v-if="showThinkingTail(m)" class="thinking-tail">
                <span>正在思考...</span>
              </div>

              <!-- expand/collapse for long user messages -->
              <button
                v-if="m.role === 'user' && isLongUserMsg(m)"
                class="bubble-expand-btn"
                @click="toggleExpandMsg(m)"
              >
                {{ expandedMsgs[getMsgKey(m)] ? '收起' : '展开' }}
                <svg :class="['bubble-expand-chevron', { rotated: expandedMsgs[getMsgKey(m)] }]" viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 6 8 10 12 6"/></svg>
              </button>

              <!-- assistant message action bar (copy + favorite) -->
              <div
                v-if="m.role === 'assistant' && m.content_json?.text && !m._streaming"
                class="msg-actions"
              >
                <button class="msg-action" @click="copyAnswer(m)" title="复制回答">
                  <el-icon :size="14"><DocumentCopy /></el-icon>
                  <span>复制</span>
                </button>
                <button
                  class="msg-action"
                  :class="{ active: isFavorited(m) }"
                  @click="toggleFavorite(m)"
                  :title="isFavorited(m) ? '取消收藏' : '收藏到空间'"
                >
                  <el-icon :size="14">
                    <StarFilled v-if="isFavorited(m)" />
                    <Star v-else />
                  </el-icon>
                  <span>{{ isFavorited(m) ? '已收藏' : '收藏' }}</span>
                </button>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- Composer -->
      <div class="composer-wrap">
        <!-- Approval panel: sits directly above the input box (same width) so a
             blocked tool execution is always visible & confirmable. -->
        <transition name="perm-float">
          <div v-if="pendingPerms.length" class="perm-float">
            <div class="perm-float-head">
              <span class="perm-float-dot" />
              <span class="perm-float-label">需要你确认是否继续执行</span>
              <span v-if="pendingPerms.length > 1" class="perm-float-count">{{ pendingPerms.length }} 项待处理</span>
            </div>
            <div class="perm-float-list">
              <div
                v-for="req in pendingPerms"
                :key="req.request_id"
                :class="['perm-card', 'pending', { 'is-high': req.risk === 'high' }]"
              >
                <div class="perm-head">
                  <el-icon class="perm-icon"><Lock /></el-icon>
                  <span class="perm-title">{{ permHeadText(req) }}</span>
                  <span class="perm-tool">{{ req.tool_name }}</span>
                </div>
                <div class="perm-body">
                  <div class="perm-reason">{{ req.reason }}</div>
                  <pre v-if="req.summary" class="perm-summary">{{ req.summary }}</pre>
                  <div class="perm-actions">
                    <button class="perm-btn allow" :disabled="req._busy" @click="answerPermission(req, 'allow', 'once')">允许本次</button>
                    <button class="perm-btn allow-session" :disabled="req._busy" @click="answerPermission(req, 'allow', 'session')">本会话都允许 {{ req.tool_name }}</button>
                    <button class="perm-btn deny" :disabled="req._busy" @click="answerPermission(req, 'deny', 'once')">拒绝</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </transition>
        <div v-if="chat.pendingFiles.length" class="files-row">
          <div
            v-for="f in chat.pendingFiles"
            :key="f.id"
            :class="['file-chip', f.parse_status]"
            :title="f.parse_error || f.name"
          >
            <el-icon class="chip-leading" v-if="f.parse_status === 'parsing'" :size="14"><Loading class="spin" /></el-icon>
            <el-icon class="chip-leading ok" v-else-if="f.parse_status === 'done'" :size="14"><CircleCheckFilled /></el-icon>
            <el-icon class="chip-leading err" v-else-if="f.parse_status === 'failed'" :size="14"><CircleCloseFilled /></el-icon>
            <el-icon class="chip-leading" v-else :size="14"><Paperclip /></el-icon>
            <span class="chip-name">{{ f.name }}</span>
            <span v-if="f.parse_status === 'done'" class="chip-meta">{{ f.parsed_chars }} 字</span>
            <span v-else-if="f.parse_status === 'parsing'" class="chip-meta">解析中</span>
            <span v-else-if="f.parse_status === 'skipped'" class="chip-meta">原始文件</span>
            <button v-else-if="f.parse_status === 'failed'" class="chip-action" @click="retryFile(f)" title="重试">重试</button>
            <button v-if="canPreview(f)" class="chip-action" @click="openPreview(f)" title="预览">
              <el-icon :size="12"><View /></el-icon>
            </button>
            <button class="chip-close" @click="removeFile(f)" title="移除">
              <el-icon :size="12"><Close /></el-icon>
            </button>
          </div>
        </div>
        <div class="composer-shell">
          <!-- Command palette (triggered by typing "/") -->
          <div v-if="cmdOpen && cmdItems.length" ref="cmdPaletteRef" class="cmd-palette" @click.stop>
            <template v-for="(it, i) in cmdItems" :key="it.key">
              <div v-if="it.groupHead" class="cmd-group">{{ it.groupHead }}</div>
              <div
                v-else
                :class="['cmd-item', { active: i === cmdIndex }]"
                :data-cmd-idx="i"
                @mouseenter="cmdIndex = i" @click="applyCommand(it)"
              >
                <el-icon class="cmd-ico"><component :is="it.icon" /></el-icon>
                <span class="cmd-name">{{ it.name }}</span>
                <span v-if="it.desc" class="cmd-desc">{{ it.desc }}</span>
                <span v-if="it.tag" class="cmd-tag">{{ it.tag }}</span>
              </div>
            </template>
          </div>
          <!-- Expert mention picker (triggered by typing "@") -->
          <div v-if="atOpen && atItems.length" class="cmd-palette at-palette" @click.stop>
            <div class="cmd-hint">@ 指派专家执行任务 — ↑↓ 选择，Enter 确认，Esc 关闭</div>
            <div
              v-for="(a, i) in atItems" :key="a.id"
              :class="['cmd-item', { active: i === atIndex }]"
              @mouseenter="atIndex = i" @click="applyMention(a)"
            >
              <el-icon class="cmd-ico"><Avatar /></el-icon>
              <span class="cmd-label">{{ a.name }}</span>
              <span class="cmd-kind">{{ a.description ? String(a.description).slice(0, 24) : '专家' }}</span>
            </div>
          </div>

          <div class="composer">
            <HomePet
              v-if="isHome"
              class="composer-pet"
              :clickable="!!chat.currentAgent"
              :title="chat.currentAgent ? '查看专家能力' : ''"
              @activate="openCurrentAgentCapabilities"
            />
            <!-- Active mention chip: this task will be dispatched to this expert -->
            <div v-if="mentionedExpert" class="mention-bar">
              <span class="mention-chip">
                <el-icon :size="13"><Avatar /></el-icon>
                指派给：{{ mentionedExpert.name }}
                <button class="mention-clear" @click="clearMention" title="取消指派"><el-icon :size="12"><Close /></el-icon></button>
              </span>
            </div>
            <!-- 生成器 chip: shown when a builder skill is active (create_expert →
                 专家生成器, create_task → 自动化任务生成器). Dark background per
                 design. Sits inline to the left of the input so the prefilled
                 instruction follows on the same line instead of wrapping below. -->
            <div class="composer-input-row" :class="{ 'has-builder': builderSkill }">
              <span v-if="builderSkill" class="builder-chip">
                <el-icon :size="13"><MagicStick /></el-icon>
                {{ builderLabel }}
                <button class="builder-clear" @click="clearBuilder" title="取消">
                  <el-icon :size="12"><Close /></el-icon>
                </button>
              </span>
              <el-input
                v-model="input"
                type="textarea"
                :rows="1"
                autosize
                resize="none"
                :placeholder="chat.currentAgent ? '今天帮你做什么...（输入 @ 指派专家，输入 / 调用指令）' : '请联系管理员授权可用的专家'"
                :disabled="sending || !chat.currentAgent"
                @input="onInputChange"
                @keydown="onComposerKeydown"
              />
            </div>
            <div class="composer-toolbar">
              <div class="composer-toolbar-left">
                <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" multiple>
                  <button class="icon-btn subtle" :disabled="!chat.currentAgent" :title="'上传文件'">
                    <el-icon :size="18"><Plus /></el-icon>
                  </button>
                </el-upload>
                <el-dropdown v-if="!isDefaultAgentActive" trigger="click" @command="onPickAgent" popper-class="agent-select-popper">
                  <button class="tool-chip agent-chip" :disabled="!chat.agents.length"
                          :title="'切换专家'">
                    <img class="agent-chip-avatar" :src="agentAvatarSrc(chat.currentAgent)" alt="" />
                    <span class="agent-chip-name">{{ chat.currentAgent?.name || '选择专家' }}</span>
                  </button>
                  <template #dropdown>
                    <el-dropdown-menu class="agent-select-menu">
                      <el-dropdown-item v-if="!chat.agents.length" command="__none__">
                        暂无可用专家
                      </el-dropdown-item>
                      <el-dropdown-item v-for="a in chat.agents" :key="a.id" :command="a.id">
                        <span class="agent-select-option">
                          <img class="agent-select-avatar" :src="agentAvatarSrc(a)" alt="" />
                          <span class="agent-select-name">{{ a.name }}</span>
                          <span v-if="a.id === chat.currentAgent?.id" class="dd-hint">当前</span>
                        </span>
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <el-dropdown v-if="!engineSelfManaged" trigger="click" @command="onPickModel">
                  <button class="tool-chip model-chip"><el-icon :size="14"><Cpu /></el-icon> {{ selectedModelLabel }}</button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item v-if="!models.length" command="__settings__">
                        未配置模型 · 前往设置添加 →
                      </el-dropdown-item>
                      <el-dropdown-item :command="null">
                        自动（默认模型）<span v-if="autoDefaultName" class="dd-hint"> · {{ autoDefaultName }}</span>
                      </el-dropdown-item>
                      <el-dropdown-item v-for="m in models" :key="m.id" :command="m.id">
                        {{ m.code || m.model_id }}
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <span v-else class="tool-chip model-chip is-cli" :title="engineSelfManagedTip">
                  <el-icon :size="14"><Cpu /></el-icon> {{ effectiveEngineLabel }}
                </span>
                <el-popover v-model:visible="skillsPopoverOpen" placement="top-start" :width="336" trigger="click"
                            popper-class="apps-popover">
                  <template #reference>
                    <button class="tool-chip" :class="{ active: selectedSkills.length }"
                            :disabled="!chat.currentAgent" title="技能"
                            @click="onSkillsOpen">
                      <el-icon :size="14"><MagicStick /></el-icon>
                      技能<span v-if="selectedSkills.length" class="apps-badge">{{ selectedSkills.length }}</span>
                    </button>
                  </template>
                  <div class="apps-pop">
                    <div class="apps-pop-head">选择技能</div>
                    <div v-if="skillsLoading" class="apps-pop-empty">加载中…</div>
                    <div v-else-if="!allSkills.length" class="apps-pop-empty">
                      还没有可用的技能，去「插件 → 技能」添加吧
                    </div>
                    <div v-else class="apps-pop-list">
                      <div v-for="sk in allSkills" :key="sk.id" class="apps-pop-item">
                        <div class="apps-pop-icon"><el-icon :size="16"><MagicStick /></el-icon></div>
                        <div class="apps-pop-main">
                          <div class="apps-pop-name">{{ sk.name || sk.code }}</div>
                          <div class="apps-pop-sum">{{ sk.user_summary || sk.description || sk.code }}</div>
                        </div>
                        <button v-if="selectedSkillIds.has(sk.id)" class="apps-pop-btn connected"
                                @click="toggleSkill(sk)">已选</button>
                        <button v-else class="apps-pop-btn" @click="toggleSkill(sk)">选择</button>
                      </div>
                    </div>
                    <a class="apps-pop-add" @click="goAddSkill">+ 添加技能</a>
                  </div>
                </el-popover>
                <el-popover v-model:visible="appsPopoverOpen" placement="top-start" :width="336" trigger="click"
                            popper-class="apps-popover">
                  <template #reference>
                    <button class="tool-chip" :class="{ active: connectedApps.length }"
                            :disabled="!chat.currentAgent" title="连应用"
                            @click="onAppsOpen">
                      <el-icon :size="14"><Connection /></el-icon>
                      连应用<span v-if="connectedApps.length" class="apps-badge">{{ connectedApps.length }}</span>
                    </button>
                  </template>
                  <div class="apps-pop">
                    <div class="apps-pop-head">连接应用</div>
                    <div v-if="!cliApps.length" class="apps-pop-empty">
                      还没有已安装的应用，去「插件 → 连接应用」连接吧
                    </div>
                    <div v-else class="apps-pop-list">
                      <div v-for="app in cliApps" :key="app.id" class="apps-pop-item">
                        <div class="apps-pop-icon"><el-icon :size="16"><Connection /></el-icon></div>
                        <div class="apps-pop-main">
                          <div class="apps-pop-name">{{ app.name }}</div>
                          <div class="apps-pop-sum">{{ app.summary || app.bin_name }}</div>
                        </div>
                        <button v-if="connectedAppIds.has(app.id)" class="apps-pop-btn connected"
                                @click="toggleApp(app)">已连接</button>
                        <button v-else class="apps-pop-btn" :disabled="app.status !== 'installed'"
                                @click="toggleApp(app)">{{ app.status === 'installed' ? '连接' : '未安装' }}</button>
                      </div>
                    </div>
                  </div>
                </el-popover>
              </div>
              <div class="composer-toolbar-right">
                <el-dropdown trigger="click" @command="onPickPermission" popper-class="perm-dropdown">
                  <button class="tool-chip permission-chip" :class="{ active: permissionMode !== 'ask' }">
                    <el-icon :size="14"><Lock /></el-icon>
                    {{ permissionLabel }}
                  </button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item v-for="o in PERMISSION_OPTIONS" :key="o.value" :command="o.value">
                        <div class="perm-opt"><b>{{ o.label }}</b><span>{{ o.desc }}</span></div>
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <button v-if="sending" class="stop-btn" title="停止生成" @click="stopStream">
                  <el-icon class="stop-spin" :size="22"><Loading /></el-icon>
                </button>
                <button v-else class="send-btn" :disabled="!input.trim() || !chat.currentAgent" @click="send">
                  <el-icon :size="18"><Promotion /></el-icon>
                </button>
              </div>
            </div>
          </div>
        </div>
        <div class="composer-underbar">
          <button class="tool-chip workspace-chip" :class="{ active: ws.current }" @click="chooseWorkspace">
            <el-icon :size="14"><Folder /></el-icon>
            <span v-if="ws.current" class="ws-name" :title="ws.current.path">{{ ws.current.name }}</span>
            <span v-else>选择工作目录</span>
          </button>
          <span v-if="ws.current" class="ws-path mono" :title="ws.current.path">{{ ws.current.path }}</span>
          <button v-if="ws.current" class="ws-clear" title="清除工作目录(改为纯对话)" @click="ws.select(null)">
            <el-icon :size="13"><Close /></el-icon>
          </button>
        </div>
      </div>
    </section>
    <PreviewPanel v-if="previewFile" :file="previewFile" @close="closePreview" />
    <AgentCapabilityDrawer
      v-model="capDrawerVisible"
      :agent-id="capDrawerAgentId"
      :agent-name="chat.currentAgent?.name"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import { useChat } from '@/stores/chat'
import { useSpace } from '@/stores/space'
import { useAuth } from '@/stores/auth'
import MarkdownIt from 'markdown-it'
import type Token from 'markdown-it/lib/token.mjs'
import WidgetRenderer from '@/components/WidgetRenderer.vue'
import FileCard from '@/components/FileCard.vue'
import PackProgressCard from '@/components/PackProgressCard.vue'
import PreviewPanel from '@/components/PreviewPanel.vue'
import AgentCapabilityDrawer from '@/components/AgentCapabilityDrawer.vue'
import HomePet from '@/components/HomePet.vue'
import MessageDispatcher from '@/agent-ui/engine/MessageDispatcher.vue'
import { InfoFilled, Loading } from '@element-plus/icons-vue'
import { parseMessageContent } from '@/lib/widget-parser'
import { resolveToolMeta } from '@/lib/toolDisplay'

const md = new MarkdownIt({ breaks: true, linkify: true })
const DEFAULT_AGENT_AVATAR = `data:image/svg+xml,${encodeURIComponent(`
<svg width="80" height="80" viewBox="0 0 80 80" xmlns="http://www.w3.org/2000/svg">
  <rect width="80" height="80" rx="22" fill="#C96442"/>
  <g fill="none" stroke="#fff" stroke-width="4.6" stroke-linecap="round" stroke-linejoin="round">
    <path d="M22 30 40 20 58 30v20L40 60 22 50Z"/>
    <path d="M22 30 40 40l18-10M22 50l18-10 18 10M40 20v20M40 40v20"/>
    <circle cx="40" cy="40" r="7" fill="#C96442"/>
  </g>
</svg>
`)}`

function isImageIcon(icon: string | null | undefined) {
  const s = String(icon || '').trim()
  return /^data:image\//i.test(s) || /^https?:\/\//i.test(s) || s.startsWith('/')
}
function agentAvatarSrc(agent: any) {
  return isImageIcon(agent?.icon) ? String(agent.icon).trim() : DEFAULT_AGENT_AVATAR
}
function escapeHtml(s: string): string {
  return md.utils.escapeHtml(s || '')
}
function escapeAttr(s: string): string {
  return md.utils.escapeHtml(s || '').replace(/"/g, '&quot;')
}
function codeLangLabel(info: string): string {
  const lang = String(info || '').trim().split(/\s+/)[0]
  return lang ? lang.toUpperCase() : 'CODE'
}
function compactUrlLabel(url: string, fallback = ''): string {
  const text = String(fallback || '').trim()
  const raw = String(url || '').trim()
  const normalizedText = text.replace(/^https?:\/\//i, '').replace(/\/$/, '')
  const normalizedUrl = raw.replace(/^https?:\/\//i, '').replace(/\/$/, '')
  if (text && normalizedText !== normalizedUrl) return text
  try {
    const u = new URL(raw)
    const host = u.hostname.replace(/^www\./, '')
    const path = u.pathname && u.pathname !== '/' ? u.pathname.split('/').filter(Boolean).slice(0, 2).join(' / ') : ''
    return path ? `${host} · ${decodeURIComponent(path)}` : host
  } catch {
    return text || raw
  }
}
function setupMarkdownRenderer() {
  md.core.ruler.push('compact_smart_links', (state) => {
    for (const block of state.tokens) {
      const children = block.children
      if (!children?.length) continue
      for (let i = 0; i < children.length - 2; i++) {
        const open = children[i]
        const text = children[i + 1]
        const close = children[i + 2]
        const href = open.type === 'link_open' ? (open.attrGet('href') || '') : ''
        if (!/^https?:\/\//i.test(href)) continue
        if (text.type === 'text' && close.type === 'link_close') {
          text.content = compactUrlLabel(href, text.content)
        }
      }
    }
  })
  const defaultFence = md.renderer.rules.fence?.bind(md.renderer.rules)
  md.renderer.rules.fence = (tokens: Token[], idx: number, options, env, self) => {
    const token = tokens[idx]
    const code = token.content || ''
    const lang = codeLangLabel(token.info || '')
    const highlighted = defaultFence
      ? defaultFence(tokens, idx, options, env, self)
      : `<pre><code>${escapeHtml(code)}</code></pre>`
    return `<div class="code-shell" data-code="${escapeAttr(code)}" data-lang="${escapeAttr(lang.toLowerCase())}">
      <div class="code-tools">
        <span class="code-lang">${escapeHtml(lang)}</span>
        <button type="button" class="code-action" data-md-action="copy-code">复制</button>
        <button type="button" class="code-action" data-md-action="run-code">执行</button>
      </div>
      ${highlighted}
    </div>`
  }

  const defaultLinkOpen = md.renderer.rules.link_open || ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))
  md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
    const token = tokens[idx]
    const href = token.attrGet('href') || ''
    if (/^https?:\/\//i.test(href)) {
      token.attrSet('class', 'smart-link')
      token.attrSet('data-url', href)
      token.attrSet('target', '_blank')
      token.attrSet('rel', 'noreferrer')
      token.attrSet('title', href)
    }
    return defaultLinkOpen(tokens, idx, options, env, self)
  }
}
setupMarkdownRenderer()
const chat = useChat()
const space = useSpace()
const auth = useAuth()
const route = useRoute()
const router = useRouter()

const input = ref('')
// Whether the CURRENTLY-VIEWED conversation has an in-flight turn. Driven by the
// store (a singleton) so the streaming state — and the running turn itself —
// survives this view being unmounted when the user switches menus/conversations.
const sending = computed(() => chat.isStreaming(chat.currentConvId))

// Home (command-center) mode: no active conversation → center & enlarge the
// composer in the middle of the screen (Codex-style landing).
const isHome = computed(() => !chat.currentConvId || chat.messages.length === 0)
function greetingByHour(hour: number): string {
  if (hour >= 5 && hour < 9) return '早上好'
  if (hour >= 9 && hour < 12) return '上午好'
  if (hour >= 12 && hour < 14) return '中午好'
  if (hour >= 14 && hour < 18) return '下午好'
  if (hour >= 18 && hour < 23) return '晚上好'
  return '夜深了'
}
const homeTitle = computed(() => {
  const user = auth.user || {}
  const name = user.name || user.nickname || user.display_name || user.username || user.id || '你'
  return `${greetingByHour(new Date().getHours())}，${name} 接下来做点什么？`
})

// ── Composer toolbar: per-conversation model & permission, workspace files ──
import { useWorkspace } from '@/stores/workspace'
const ws = useWorkspace()
const models = ref<any[]>([])
const selectedModelId = ref<number | null>(null)
const permissionMode = ref<string>('ask')
const wsFilePickerVisible = ref(false)

// ── 连应用 (connected CLI apps) popover ──
const cliApps = ref<any[]>([])
const connectedApps = ref<any[]>([])
const appsPopoverOpen = ref(false)
const connectedAppIds = computed(() => new Set(connectedApps.value.map((a) => a.id)))
async function loadCliApps() {
  try {
    const all = await api.cliApps()
    // Only surface installed + enabled apps in the chat picker.
    cliApps.value = (all || []).filter((a: any) => a.enabled && a.status === 'installed')
  } catch { cliApps.value = [] }
}
function onAppsOpen() {
  if (!cliApps.value.length) loadCliApps()
}
function toggleApp(app: any) {
  if (connectedAppIds.value.has(app.id)) {
    connectedApps.value = connectedApps.value.filter((a) => a.id !== app.id)
  } else {
    connectedApps.value = [...connectedApps.value, app]
  }
}

// ── 技能 (skills) picker popover ──
const allSkills = ref<any[]>([])
const selectedSkills = ref<any[]>([])
const skillsPopoverOpen = ref(false)
const skillsLoading = ref(false)
const selectedSkillIds = computed(() => new Set(selectedSkills.value.map((s) => s.id)))
async function loadAllSkills() {
  skillsLoading.value = true
  try {
    const all = await api.skills()
    allSkills.value = (all || []).filter((s: any) => s.enabled !== false)
  } catch { allSkills.value = [] }
  finally { skillsLoading.value = false }
}
function onSkillsOpen() {
  if (!allSkills.value.length) loadAllSkills()
}
function toggleSkill(sk: any) {
  if (selectedSkillIds.value.has(sk.id)) {
    selectedSkills.value = selectedSkills.value.filter((s) => s.id !== sk.id)
  } else {
    selectedSkills.value = [...selectedSkills.value, sk]
  }
}

// Builder chips — surfaced as a dark chip in the composer when a 生成器 skill
// was pre-selected via a 自定义配置 / 对话创建 entry. Lets the user see / cancel
// the builder mode. Two builders share the same chip styling:
//   create_expert → 专家生成器 (from 专家管理)
//   create_task   → 自动化任务生成器 (from 自动化)
const BUILDER_LABELS: Record<string, string> = {
  create_expert: '专家生成器',
  create_task: '自动化任务生成器',
}
const builderSkill = computed(() =>
  selectedSkills.value.find((s: any) => BUILDER_LABELS[s.code]) || null
)
const builderLabel = computed(() =>
  builderSkill.value ? BUILDER_LABELS[builderSkill.value.code] : ''
)
function clearBuilder() {
  if (!builderSkill.value) return
  const code = builderSkill.value.code
  selectedSkills.value = selectedSkills.value.filter((s: any) => s.code !== code)
}
function goAddSkill() {
  skillsPopoverOpen.value = false
  router.push({ path: '/plugins', query: { tab: 'skills' } })
}

const PERMISSION_OPTIONS = [
  { value: 'ask', label: '默认权限', desc: '执行命令、修改文件、联网等敏感操作前，逐个弹窗等你确认；只读操作直接放行。' },
  { value: 'auto', label: '自动执行', desc: '常规文件编辑和安全命令自动执行；仅 rm -rf、sudo 等高危命令才弹窗确认。' },
  { value: 'full', label: '全权模式', desc: '全部自动执行不打断；仅极危命令（rm -rf /、mkfs 等）仍被硬性拦截。适合可信目录。' },
]
const permissionLabel = computed(() =>
  PERMISSION_OPTIONS.find((o) => o.value === permissionMode.value)?.label || '询问')
// The model that will actually be used: explicit per-conversation choice, else
// the first enabled model (the auto-default the backend resolves to).
const effectiveModel = computed(() => {
  if (selectedModelId.value != null) return models.value.find((x) => x.id === selectedModelId.value) || null
  return models.value.find((x) => x.enabled !== false) || models.value[0] || null
})
const selectedModelLabel = computed(() => {
  const m = effectiveModel.value
  if (!m) return '未配置模型'
  const name = m.code || m.model_id
  return selectedModelId.value == null ? `${name}` : name
})
// Name of the model the backend auto-picks when none is explicitly chosen.
const autoDefaultName = computed(() => {
  const m = models.value.find((x) => x.enabled !== false) || models.value[0]
  return m ? (m.code || m.model_id) : ''
})

// When the current expert's engine manages its own model (local Claude/Codex
// CLI), the app-configured model is irrelevant — hide the model selector and
// show the engine name instead.
const engineSelfManaged = computed(() => !!chat.currentAgent?.engine_self_managed_model)
const ENGINE_LABELS: Record<string, string> = {
  'claude-code-cli': 'Claude Code CLI',
  'codex-cli': 'Codex CLI',
}
const effectiveEngineLabel = computed(() => {
  const e = chat.currentAgent?.effective_engine || ''
  return ENGINE_LABELS[e] || e || '命令行引擎'
})
const engineSelfManagedTip = computed(() =>
  `该专家使用「${effectiveEngineLabel.value}」，模型由本机 CLI 挂载，无法在应用内切换`)

async function loadModels() {
  if (models.value.length) return
  try { models.value = await api.models() } catch { models.value = [] }
}

// Sync toolbar state from the active conversation.
watch(() => chat.currentConvId, (cid) => {
  const c = chat.convs.find((x: any) => x.id === cid)
  selectedModelId.value = c?.model_id ?? null
  permissionMode.value = c?.permission_mode ?? (ws.current?.permission_mode || 'ask')
})
watch(() => ws.current?.permission_mode, (mode) => {
  if (!chat.currentConvId) permissionMode.value = mode || 'ask'
})

async function onPickModel(id: number | null | string) {
  if (id === '__settings__') { router.push('/settings/models'); return }
  selectedModelId.value = (id as number | null)
  if (chat.currentConvId) {
    try {
      await api.renameConversation(chat.currentConvId, { model_id: (id as number) ?? undefined })
      const c = chat.convs.find((x: any) => x.id === chat.currentConvId)
      if (c) c.model_id = id
    } catch {}
  }
}
// Switch the active expert from the composer. Mirrors clicking a "召唤" button:
// selecting a different agent starts a fresh welcome screen for it.
function onPickAgent(id: number | string) {
  if (id === '__none__') return
  const a = chat.agents.find((x: any) => x.id === id)
  if (a && a.id !== chat.currentAgent?.id) chat.selectAgent(a)
}
async function onPickPermission(mode: string) {
  permissionMode.value = mode
  if (chat.currentConvId) {
    try {
      await api.renameConversation(chat.currentConvId, { permission_mode: mode })
      const c = chat.convs.find((x: any) => x.id === chat.currentConvId)
      if (c) c.permission_mode = mode
    } catch {}
  }
}
// Insert an @workspace-file reference into the input.
function insertWorkspaceFile(entry: any) {
  const ref = `@${entry.path} `
  input.value = (input.value ? input.value.trimEnd() + ' ' : '') + ref
  wsFilePickerVisible.value = false
}

async function chooseWorkspace() {
  if (!ws.isDesktop) {
    ElMessage.info('请在桌面客户端中选择工作目录')
    return
  }
  await ws.addViaPicker()
}

// ── "/" command palette (commands · skills · experts) ──
import {
  QuestionFilled as IcoHelp, Delete as IcoClear, Coin as IcoCost, Compass as IcoCompact,
  FirstAidKit as IcoDoctor, DocumentAdd as IcoInit, View as IcoReview, Monitor as IcoTerminal,
  Notebook as IcoMemory, MagicStick as IconSkill, Avatar as IconExpert, Compass as IconCmd,
} from '@element-plus/icons-vue'
const cmdOpen = ref(false)
const cmdIndex = ref(0)
const cmdFilter = ref('')
const cmdPaletteRef = ref<HTMLElement | null>(null)

function closeInlinePickers() {
  cmdOpen.value = false
  atOpen.value = false
}

function onDocumentPointerDown(e: PointerEvent) {
  if (!cmdOpen.value && !atOpen.value) return
  const target = e.target as HTMLElement | null
  if (target?.closest('.composer-shell')) return
  closeInlinePickers()
}

// Keep the highlighted command row scrolled into view as the user arrows
// through a long list.
watch(cmdIndex, async () => {
  if (!cmdOpen.value) return
  await nextTick()
  const root = cmdPaletteRef.value
  if (!root) return
  const el = root.querySelector(`[data-cmd-idx="${cmdIndex.value}"]`) as HTMLElement | null
  if (el) el.scrollIntoView({ block: 'nearest' })
})

// Built-in slash commands. `action` decides what applyCommand does:
//   'insert'  → append `insert` text to the input as a task prefix
//   'builtin' → run a client-side action (clear / cost / review / …)
// const BUILTIN_COMMANDS = [
//   { key: 'cmd:help',     name: 'help',            desc: '显示可用命令和提示',        action: 'builtin', icon: IcoHelp },
//   { key: 'cmd:clear',    name: 'clear',           desc: '清除对话历史',              action: 'builtin', icon: IcoClear },
//   { key: 'cmd:cost',     name: 'cost',            desc: '显示 Token 用量统计',       action: 'builtin', icon: IcoCost },
//   { key: 'cmd:compact',  name: 'compact',         desc: '压缩对话上下文',            action: 'builtin', icon: IcoCompact },
//   { key: 'cmd:doctor',   name: 'doctor',          desc: '诊断项目健康状况',          action: 'insert', icon: IcoDoctor, insert: '请诊断当前项目的健康状况（依赖、配置、潜在问题）：' },
//   { key: 'cmd:init',     name: 'init',            desc: '初始化项目 CLAUDE.md',      action: 'insert', icon: IcoInit, insert: '请扫描当前工作目录并生成一份 CLAUDE.md（项目说明、结构、约定）。' },
//   { key: 'cmd:review',   name: 'review',          desc: '审查代码质量',              action: 'insert', icon: IcoReview, insert: '请审查当前改动的代码质量与潜在问题：' },
//   { key: 'cmd:terminal', name: 'terminal-setup',  desc: '配置终端设置',              action: 'builtin', icon: IcoTerminal },
//   { key: 'cmd:memory',   name: 'memory',          desc: '编辑项目记忆文件',          action: 'insert', icon: IcoMemory, insert: '请打开并编辑项目记忆文件 CLAUDE.md：' },
// ]
const BUILTIN_COMMANDS = [
  { key: 'cmd:help',     name: '帮助',            desc: '显示可用命令和提示',        action: 'builtin', icon: IcoHelp },
  { key: 'cmd:clear',    name: '清除',           desc: '清除对话历史',              action: 'builtin', icon: IcoClear },
  { key: 'cmd:cost',     name: '用量',            desc: '显示 Token 用量统计',       action: 'builtin', icon: IcoCost },
  { key: 'cmd:compact',  name: '压缩',         desc: '压缩对话上下文',            action: 'builtin', icon: IcoCompact },
  { key: 'cmd:doctor',   name: '健康检查',          desc: '诊断项目健康状况',          action: 'insert', icon: IcoDoctor, insert: '请诊断当前项目的健康状况（依赖、配置、潜在问题）：' },
  { key: 'cmd:memory',   name: '记忆',          desc: '编辑项目记忆文件',          action: 'insert', icon: IcoMemory, insert: '请打开并编辑项目记忆文件 CLAUDE.md：' },
  { key: 'cmd:health',   name: '健康检查',    desc: '系统健康检查（模型 / 专家）', action: 'builtin', icon: IcoDoctor },
]
const allCommandItems = computed(() => {
  const items: any[] = []
  // ── Commands ──
  items.push({ key: 'g:cmd', groupHead: 'Commands' })
  for (const c of BUILTIN_COMMANDS) items.push({ ...c, kind: 'command' })
  // ── Expert Skills ──
  if (skillCatalog.value.length) {
    items.push({ key: 'g:skill', groupHead: '技能' })
    for (const sk of skillCatalog.value) {
      items.push({
        key: 'skill:' + sk.id,
        name: sk.code || sk.name,
        desc: sk.description || sk.name || '',
        tag: sk.source || (sk.type === 'composite' ? '组合技能' : 'Personal'),
        kind: 'skill', icon: IconSkill,
        action: 'insert',
        insert: `请使用「${sk.name || sk.code}」技能完成：`,
      })
    }
  }
  return items
})

// Visible (filtered) list — group heads are kept only when their group has hits.
const cmdItems = computed(() => {
  const f = cmdFilter.value.toLowerCase()
  const all = allCommandItems.value
  if (!f) return all
  const out: any[] = []
  let pendingHead: any = null
  for (const it of all) {
    if (it.groupHead) { pendingHead = it; continue }
    const hay = `${it.name} ${it.desc || ''}`.toLowerCase()
    if (hay.includes(f)) {
      if (pendingHead) { out.push(pendingHead); pendingHead = null }
      out.push(it)
    }
  }
  return out
})

// Index of selectable rows only (skip group heads) for keyboard nav.
function nextSelectable(from: number, dir: 1 | -1): number {
  const list = cmdItems.value
  if (!list.length) return from
  let i = from
  for (let n = 0; n < list.length; n++) {
    i = (i + dir + list.length) % list.length
    if (!list[i].groupHead) return i
  }
  return from
}

// Skill catalog for the "/" palette. Loads ALL installed & enabled skills
// (not just the current expert's) so users can invoke any installed skill.
const skillCatalog = ref<any[]>([])
async function loadSkillCatalog() {
  try {
    const all = await api.skills()
    skillCatalog.value = (all || []).filter((s: any) => s.enabled !== false)
  } catch { skillCatalog.value = [] }
}

function detectSlash(): { active: boolean; filter: string } {
  const v = input.value
  // Only fire when "/" is at line start or after whitespace, with no spaces after.
  const m = v.match(/(^|\s)\/([^\s/]*)$/)
  if (m) return { active: true, filter: m[2] }
  return { active: false, filter: '' }
}

function onInputChange() {
  const d = detectSlash()
  if (d.active) {
    if (!cmdOpen.value) { cmdOpen.value = true; loadSkillCatalog() }
    cmdFilter.value = d.filter
    // Land on the first selectable (non-group-head) row.
    cmdIndex.value = cmdItems.value.findIndex((x: any) => !x.groupHead)
    atOpen.value = false
    return
  }
  cmdOpen.value = false
  // "@" expert mention
  const at = detectAt()
  if (at.active) {
    if (!atOpen.value) { atOpen.value = true; atIndex.value = 0 }
    atFilter.value = at.filter
  } else {
    atOpen.value = false
  }
}

function onComposerKeydown(e: KeyboardEvent) {
  if (cmdOpen.value && cmdItems.value.length) {
    if (e.key === 'ArrowDown') { e.preventDefault(); cmdIndex.value = nextSelectable(cmdIndex.value, 1); return }
    if (e.key === 'ArrowUp') { e.preventDefault(); cmdIndex.value = nextSelectable(cmdIndex.value, -1); return }
    if (e.key === 'Enter') {
      e.preventDefault()
      const it = cmdItems.value[cmdIndex.value]
      if (it && !it.groupHead) applyCommand(it)
      return
    }
    if (e.key === 'Escape') { e.preventDefault(); cmdOpen.value = false; return }
  }
  if (atOpen.value && atItems.value.length) {
    if (e.key === 'ArrowDown') { e.preventDefault(); atIndex.value = (atIndex.value + 1) % atItems.value.length; return }
    if (e.key === 'ArrowUp') { e.preventDefault(); atIndex.value = (atIndex.value - 1 + atItems.value.length) % atItems.value.length; return }
    if (e.key === 'Enter') { e.preventDefault(); applyMention(atItems.value[atIndex.value]); return }
    if (e.key === 'Escape') { e.preventDefault(); atOpen.value = false; return }
  }
  // Default: Enter sends (when no palette open).
  if (e.key === 'Enter' && !e.shiftKey && !cmdOpen.value && !atOpen.value) { e.preventDefault(); send() }
}

function applyCommand(it: any) {
  if (!it || it.groupHead) return
  // Strip the trailing "/filter" token from the input.
  input.value = input.value.replace(/(^|\s)\/[^\s/]*$/, (m, p1) => p1 || '')
  cmdOpen.value = false
  if (it.action === 'builtin') {
    runBuiltinCommand(it.key)
    return
  }
  // 'insert' — append the prompt prefix so the user types the rest of the task.
  if (it.insert) {
    input.value = (input.value ? input.value.trimEnd() + ' ' : '') + it.insert
  }
}

// Client-side built-in command handlers.
function runBuiltinCommand(key: string) {
  switch (key) {
    case 'cmd:help':
      ElMessage.info('输入 / 调用命令与技能，输入 @ 指派专家执行任务')
      break
    case 'cmd:clear':
      chat.newConv()
      ElMessage.success('已清除当前对话')
      break
    case 'cmd:cost':
      router.push('/settings/usage')
      break
    case 'cmd:health':
      router.push('/settings/health')
      break
    case 'cmd:compact':
      input.value = '请用要点总结到目前为止的对话上下文，后续基于该摘要继续。'
      break
    case 'cmd:terminal':
      ElMessage.info('终端在右侧面板「终端」标签中，工作目录为当前项目目录')
      break
    default:
      break
  }
}

// ── "@" expert mention: dispatch this task to a specific expert ──
const atOpen = ref(false)
const atIndex = ref(0)
const atFilter = ref('')
// The expert this task will be dispatched to (null = current expert).
const mentionedExpert = ref<any | null>(null)

const atItems = computed(() => {
  const f = atFilter.value.toLowerCase()
  const list = (chat.agents || [])
  if (!f) return list.slice(0, 8)
  return list.filter((a: any) =>
    (a.name || '').toLowerCase().includes(f) || (a.code || '').toLowerCase().includes(f)
  ).slice(0, 8)
})

function detectAt(): { active: boolean; filter: string } {
  const v = input.value
  // Fire when "@" is at line start or after whitespace, with no spaces after.
  const m = v.match(/(^|\s)@([^\s@]*)$/)
  if (m) return { active: true, filter: m[2] }
  return { active: false, filter: '' }
}

function applyMention(a: any) {
  // Remove the trailing "@filter" token; mark this expert as the target.
  input.value = input.value.replace(/(^|\s)@[^\s@]*$/, (m, p1) => p1 || '')
  mentionedExpert.value = a
  // Switch the active expert so the right panel / capabilities reflect it too.
  chat.selectAgent(a)
  atOpen.value = false
}

function clearMention() {
  mentionedExpert.value = null
}

function stopStream() {
  // Abort the active conversation's in-flight turn (runs in the store, so this
  // works even after navigating away and back).
  chat.stopStream()
}

const expandedMsgs = ref<Record<string, boolean>>({})
function getMsgKey(m: any) { return String(m.id ?? m._tmp ?? '') }
function toggleExpandMsg(m: any) {
  const key = getMsgKey(m)
  expandedMsgs.value[key] = !expandedMsgs.value[key]
}
function isLongUserMsg(m: any) {
  const text = m.content_json?.text || ''
  return text.length > 400 || text.split('\n').length > 8
}

const scrollRef = ref<HTMLElement | null>(null)
const previewFile = ref<any | null>(null)
const capDrawerVisible = ref(false)
const capDrawerAgentId = ref<number | null>(null)
function openCapabilities(agentId: number) {
  capDrawerAgentId.value = agentId
  capDrawerVisible.value = true
}

// Hide the composer expert selector when the active expert is the default one.
// Other entry points (e.g. 召唤专家) switch to a non-default expert, where the
// selector stays visible so the user can switch back.
const isDefaultAgentActive = computed(() => {
  const cur = chat.currentAgent
  if (!cur) return false
  if (cur.is_default) return true
  const def = chat.defaultAgent
  return !!(def && def.id === cur.id)
})

// Clicking the floating home pet opens the same capability drawer used by the
// 技能能力 action in 专家管理, scoped to the currently active expert.
function openCurrentAgentCapabilities() {
  const id = chat.currentAgent?.id
  if (id != null) openCapabilities(id)
}

/** Split the current agent's description into a plain intro paragraph and a
 *  list of starter questions. Lines starting with '- ', '• ', '* ' or a
 *  numbered prefix like '1.' are treated as starter questions; everything
 *  else joins the intro. */
const parsedWelcome = computed<{ intro: string; starters: string[] }>(() => {
  const desc = chat.currentAgent?.description || ''
  if (!desc) return { intro: '', starters: [] }
  const starterRe = /^\s*(?:[-•*]|\d+[.、])\s+(.+)$/
  const introLines: string[] = []
  const starters: string[] = []
  for (const raw of desc.split(/\r?\n/)) {
    const m = raw.match(starterRe)
    if (m && m[1].trim()) {
      starters.push(m[1].trim())
    } else if (raw.trim()) {
      introLines.push(raw.trim())
    }
  }
  return { intro: introLines.join(' '), starters: starters.slice(0, 4) }
})
const welcomeIntro = computed(() => parsedWelcome.value.intro)
const welcomeStarters = computed(() => parsedWelcome.value.starters)

function useStarter(q: string) {
  if (!q || sending.value || !chat.currentAgent) return
  input.value = q
  send()
}

function closePreview() { previewFile.value = null }

// "Jump back to original conversation" support — Space.vue routes to
// /chat?msg=<id> after selectConv-ing the right conversation. We then scroll
// that message into view and flash a highlight ring on it for ~1.6s.
const highlightedMessageId = ref<number | null>(null)
let highlightTimer: any = null
async function scrollToMessage(messageId: number) {
  if (!messageId) return
  for (let i = 0; i < 12; i++) {
    await nextTick()
    const el = document.querySelector(`.msg[data-mid="${messageId}"]`) as HTMLElement | null
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      highlightedMessageId.value = messageId
      if (highlightTimer) clearTimeout(highlightTimer)
      highlightTimer = setTimeout(() => { highlightedMessageId.value = null }, 1600)
      return
    }
    await new Promise((r) => setTimeout(r, 80))  // wait for messages to render
  }
}

onMounted(async () => {
  document.addEventListener('pointerdown', onDocumentPointerDown, true)
  if (!chat.loaded) await chat.loadInit()
  // Even if the store was already loaded, refresh agents so engine-derived
  // fields (effective_engine / engine_self_managed_model, which drive the model
  // selector vs. CLI-engine chip) reflect any change made in the admin 执行引擎
  // page during this session. Best-effort; never blocks the view.
  else chat.reloadAgents().catch(() => {})
  loadModels()
  // Deep-link: /chat?conv=N opens an existing conversation (e.g. from a task run).
  const convQuery = route.query.conv
  const convId = Array.isArray(convQuery) ? Number(convQuery[0]) : Number(convQuery)
  if (convId && !Number.isNaN(convId) && convId !== chat.currentConvId) {
    let conv = chat.convs.find((c: any) => c.id === convId)
    if (!conv) conv = { id: convId }
    try { await chat.selectConv(conv) } catch {}
  }
  await scrollBottom()
  // Deep-link: /chat?msg=N highlights & scrolls to that message.
  const msgQuery = route.query.msg
  const msgId = Array.isArray(msgQuery) ? Number(msgQuery[0]) : Number(msgQuery)
  if (msgId && !Number.isNaN(msgId)) await scrollToMessage(msgId)
  // Deep-link: /chat?draft=...&skill=create_expert — prefill the composer and
  // pre-select a built-in skill so the user can describe an expert and have the
  // 专家生成器 skill create it on send (自定义配置入口 from 专家管理).
  await applyDraftFromQuery()
})

// Prefill composer text + pre-select a skill from the route query, then strip
// those params so a refresh / back-nav doesn't re-trigger them.
async function applyDraftFromQuery() {
  const draftQ = route.query.draft
  const draft = Array.isArray(draftQ) ? draftQ[0] : draftQ
  const skillQ = route.query.skill
  const skillCode = Array.isArray(skillQ) ? skillQ[0] : skillQ
  const agentQ = route.query.agent
  const agentId = Array.isArray(agentQ) ? Number(agentQ[0]) : Number(agentQ)
  if (!draft && !skillCode && !(agentId && !Number.isNaN(agentId))) return
  // 召唤: switch the composer to the requested expert. The agent may have been
  // created earlier in this same session (e.g. via 专家生成器), in which case the
  // store's cached list is stale — refresh it once before giving up so freshly
  // created experts can still be summoned.
  if (agentId && !Number.isNaN(agentId)) {
    let a = chat.agents.find((x: any) => x.id === agentId)
    if (!a) {
      await chat.reloadAgents().catch(() => {})
      a = chat.agents.find((x: any) => x.id === agentId)
    }
    if (a && a.id !== chat.currentAgent?.id) chat.selectAgent(a)
  }
  if (draft) input.value = String(draft)
  if (skillCode) {
    try {
      if (!allSkills.value.length) await loadAllSkills()
      const sk = allSkills.value.find((s: any) => s.code === skillCode)
      if (sk && !selectedSkillIds.value.has(sk.id)) {
        selectedSkills.value = [...selectedSkills.value, sk]
      }
    } catch {}
  }
  // Clear the one-shot params without adding a history entry.
  const q = { ...route.query }
  delete q.draft
  delete q.skill
  delete q.agent
  router.replace({ path: route.path, query: q })
}

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown, true)
})

watch(() => chat.currentConvId, async () => {
  closeInlinePickers()
  await scrollBottom()
})

// Re-trigger scroll when ?msg= changes while already on /chat
watch(() => route.query.msg, async (val) => {
  const id = Array.isArray(val) ? Number(val[0]) : Number(val)
  if (id && !Number.isNaN(id)) await scrollToMessage(id)
})

// The stream loop now lives in the store (so a turn survives this view being
// unmounted). The DOM side-effects it used to do inline — auto-scroll and
// thinking-panel scroll — must still run here. Drive them off the store's
// streamTick, which bumps on every applied event. Only react when the
// conversation currently being VIEWED is the one streaming, so a background
// turn in another conversation doesn't yank this view around.
watch(() => chat.streamTick, async () => {
  const cid = chat.currentConvId
  if (cid == null || !chat.isStreaming(cid)) return
  const live = chat.live[cid]
  if (live?.placeholder) scrollThinkingToBottom(live.placeholder)
  await scrollBottom()
})

async function onPick(uploadFile: any) {
  // el-upload `on-change` fires once per selected file. The actual File is on .raw
  const file: File | undefined = uploadFile?.raw
  if (!file) return
  if (!chat.currentAgent) {
    ElMessage.warning('请先选择专家')
    return
  }
  if (!chat.currentConvId) {
    await chat.ensureConv()
  }
  try {
    const r = await api.uploadFile(file, chat.currentConvId!)
    chat.pendingFiles.push(r)
    pollFileStatus(r.id)
  } catch (e: any) {
    // axios interceptor already shows ElMessage; nothing else needed
  }
}

function pollFileStatus(fileId: number) {
  const tick = async () => {
    const idx = chat.pendingFiles.findIndex((x: any) => x.id === fileId)
    if (idx === -1) return  // user removed it
    try {
      const fresh = await api.getFile(fileId)
      // splice in place to keep reactivity
      chat.pendingFiles[idx] = { ...chat.pendingFiles[idx], ...fresh }
      if (fresh.parse_status === 'parsing') {
        setTimeout(tick, 1500)
      }
    } catch {
      // file gone or transient — stop polling
    }
  }
  setTimeout(tick, 800)
}

async function retryFile(f: any) {
  try {
    const fresh = await api.reparseFile(f.id)
    const idx = chat.pendingFiles.findIndex((x: any) => x.id === f.id)
    if (idx >= 0) chat.pendingFiles[idx] = { ...chat.pendingFiles[idx], ...fresh }
    pollFileStatus(f.id)
  } catch {}
}

async function removeFile(f: any) {
  chat.pendingFiles = chat.pendingFiles.filter((x: any) => x.id !== f.id)
  // best-effort cleanup on the server
  try { await api.deleteFile(f.id) } catch {}
}

const PREVIEWABLE_EXT = new Set([
  'html', 'htm', 'pdf',
  'md', 'markdown',
  'txt', 'log', 'json', 'csv', 'xml',
  'js', 'ts', 'css', 'py', 'sql', 'yml', 'yaml', 'sh',
  'svg',
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp',
])

function canPreview(f: any): boolean {
  if (!f) return false
  const e = (f.ext || (f.name || '').split('.').pop() || '').toLowerCase().replace(/^\./, '')
  return PREVIEWABLE_EXT.has(e)
}

function openPreview(f: any) {
  // Composer-uploaded files come from /api/files; their raw bytes live at /api/files/{id}/raw.
  // Skill-output files have download_url set already. Build the right URL on the fly.
  const url = f.download_url || (f.id ? `/api/files/${f.id}/raw` : '')
  previewFile.value = { ...f, download_url: url }
}

// Bridge for UI Schema → Agent. The text carries one of two prefixes:
//   [UI_ACTION] tool=...  → backend bypasses LLM and calls the tool directly
//   [UI_MSG] <text>       → backend strips the prefix and runs the LLM normally,
//                            but the user-message it persists is marked hidden
//                            so the synthetic bubble doesn't show up in the transcript.
// Either way, we don't push a user bubble locally.
async function onAgentCall(text: string) {
  if (!chat.currentAgent || sending.value) return
  if (!chat.currentConvId) await chat.ensureConv()
  const cid = chat.currentConvId
  if (cid == null) return

  chat.messages.push({
    _tmp: Date.now(), role: 'assistant',
    content_json: { text: '' }, tool_calls_json: null,
    _meta: null, _thinking: '', _steps: [], _stepIndex: {} as Record<string, number>,
    _files: [], _uis: [], _perms: [],
    _streaming: true,
  })
  // Keep a reference to the reactive proxy (the pushed array element), not the
  // literal above — the store mutates this proxy as stream events arrive.
  const placeholder: any = chat.messages[chat.messages.length - 1]
  await scrollBottom()

  // The turn runs in the store (singleton), so it survives this view unmounting.
  await chat.streamTurn(cid, { content: text, file_ids: [] }, placeholder)
}

function renderContent(m: any) {
  const text = m.content_json?.text || ''
  return md.render(text)
}

function parseSegments(m: any) {
  const text = m.content_json?.text || ''
  return parseMessageContent(text, !!m._streaming)
}

async function copyText(text: string, okText = '已复制') {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(okText)
  } catch {
    ElMessage.error('复制失败')
  }
}

function shellCommandForCode(code: string, lang: string): string {
  const l = String(lang || '').toLowerCase()
  if (['sh', 'bash', 'zsh', 'shell'].includes(l)) return `${code.trimEnd()}\r`
  if (['py', 'python'].includes(l)) return `python3 <<'PY'\n${code.trimEnd()}\nPY\r`
  if (['js', 'javascript', 'node'].includes(l)) return `node <<'JS'\n${code.trimEnd()}\nJS\r`
  if (['ts', 'typescript'].includes(l)) return `npx tsx <<'TS'\n${code.trimEnd()}\nTS\r`
  if (['ruby', 'rb'].includes(l)) return `ruby <<'RB'\n${code.trimEnd()}\nRB\r`
  if (l === 'php') return `php <<'PHP'\n${code.trimEnd()}\nPHP\r`
  return `${code.trimEnd()}\r`
}

async function runCodeInTerminal(code: string, lang: string) {
  const desktop = (window as any).desktop
  if (!desktop?.isDesktop) {
    ElMessage.warning('请在桌面客户端中执行代码')
    return
  }
  window.dispatchEvent(new CustomEvent('workbuddy:open-terminal'))
  try {
    window.dispatchEvent(new CustomEvent('workbuddy:terminal-write', {
      detail: { data: shellCommandForCode(code, lang) },
    }))
    ElMessage.success('已发送到终端执行')
  } catch (e: any) {
    ElMessage.error(e?.message || '终端执行失败')
  }
}

async function openSmartLink(url: string) {
  const u = String(url || '')
  if (!/^https?:\/\//i.test(u)) return
  const desktop = (window as any).desktop
  if (desktop?.openURL) await desktop.openURL(u)
  else window.open(u, '_blank', 'noopener,noreferrer')
}

function onRenderedContentClick(e: MouseEvent) {
  const target = e.target as HTMLElement | null
  const actionEl = target?.closest<HTMLElement>('[data-md-action]')
  if (actionEl) {
    e.preventDefault()
    e.stopPropagation()
    const action = actionEl.dataset.mdAction
    if (action === 'copy-code' || action === 'run-code') {
      const shell = actionEl.closest<HTMLElement>('.code-shell')
      const code = shell?.dataset.code || ''
      const lang = shell?.dataset.lang || ''
      if (!code) return
      if (action === 'copy-code') copyText(code, '代码已复制')
      else runCodeInTerminal(code, lang)
      return
    }
    if (action === 'open-link') {
      openSmartLink(actionEl.dataset.url || '')
    }
    return
  }

  const linkEl = target?.closest<HTMLAnchorElement>('a.smart-link')
  const href = linkEl?.dataset.url || linkEl?.href || ''
  if (href) {
    e.preventDefault()
    e.stopPropagation()
    openSmartLink(href)
  }
}

function onWidgetSendMessage(text: string) {
  if (!text || sending.value) return
  input.value = text
  send()
}

function normalizeTrace(trace: any[] | undefined) {
  if (!Array.isArray(trace) || !trace.length) return []
  const steps: any[] = []
  const stepIndex: Record<string, number> = {}

  for (const t of trace) {
    const data = t?.data || {}
    if (t?.type === 'tool_use') {
      const id = String(data.id || data.name || `tool-${steps.length}`)
      const existingIdx = stepIndex[id]
      if (existingIdx != null) {
        const s = steps[existingIdx]
        if (data.input && (typeof data.input !== 'object' || Object.keys(data.input).length)) {
          s.input = data.input
        }
        continue
      }
      stepIndex[id] = steps.length
      const meta = resolveToolMeta(data.name || '')
      steps.push({
        kind: meta.kind,
        name: data.name || '(tool)',
        label: meta.label,
        serverName: meta.serverName,
        input: data.input,
        status: 'done',
      })
      continue
    }
    if (t?.type === 'tool_result') {
      const id = data.tool_use_id != null ? String(data.tool_use_id) : ''
      let idx = id ? stepIndex[id] : undefined
      if (idx == null) idx = steps.length - 1
      const s = steps[idx]
      if (s) {
        s.output = data.content
      }
    }
  }

  return steps
}

function formatStepData(v: any) {
  if (typeof v === 'string') {
    try { return JSON.stringify(JSON.parse(v), null, 2) } catch { return v }
  }
  return JSON.stringify(v, null, 2)
}

// -------- Thinking block: per-message scroll refs --------
const thinkingRefs = new WeakMap<object, HTMLElement>()

function setThinkingRef(el: unknown, m: object) {
  if (el instanceof HTMLElement) thinkingRefs.set(m, el)
}

function scrollThinkingToBottom(m: object) {
  nextTick(() => {
    const el = thinkingRefs.get(m)
    if (el) el.scrollTop = el.scrollHeight
  })
}

// True while we've sent the question but no visible content has come back yet.
// Hides as soon as text / thinking / tool steps / files / UIs appear.
function isWaiting(m: any): boolean {
  if (m.role !== 'assistant' || !m._streaming) return false
  if (m.content_json?.text) return false
  if (m._thinking) return false
  if (m._steps?.length) return false
  if (m._files?.length) return false
  if (m._uis?.length) return false
  return true
}

// ── Execution-process panel (dynamic, then collapses on final answer) ──
function _steps(m: any): any[] {
  return m._steps || normalizeTrace(m.tool_calls_json?.trace) || []
}
function stepCount(m: any): number { return _steps(m).length }
function stepsRunning(m: any): boolean {
  return _steps(m).some((s: any) => s.status === 'running')
}
function latestStep(m: any): any | null {
  const list = _steps(m)
  return list.length ? list[list.length - 1] : null
}
function latestStepText(m: any): string {
  const s = latestStep(m)
  if (!s) return ''
  const name = s.label || s.name || '工具调用'
  if (s.status === 'running') return `${name} 正在执行`
  if (s.status === 'done') return `${name} 已完成`
  return name
}
function showThinkingTail(m: any): boolean {
  // Keep the "正在思考" hint pinned at the bottom for the whole duration of a
  // streaming response so the user knows the model is still working — it stays
  // until the run finishes, even after partial text has appeared.
  return m.role === 'assistant' && !!m._streaming
}
// Keep the execution panel compact by default while a run is active. This
// prevents long tool chains from repeatedly changing message height as each new
// call arrives. A manual toggle (_stepsOpen set) wins.
function isStepsOpen(m: any): boolean {
  if (m._stepsOpen != null) return m._stepsOpen
  return false
}
function toggleSteps(m: any) {
  m._stepsOpen = !isStepsOpen(m)
}

// Show a slightly more informative label once the model has acknowledged
// (we got `meta`) but before any visible token.
function thinkingLabel(m: any): string {
  return m._meta ? '正在思考' : '正在连接专家'
}

// -------- Copy / Favorite (message action bar) --------

function plainTextFromMarkdown(md_src: string): string {
  // Strip common markdown markers for the plaintext clipboard slot. Keeps
  // line breaks, list bullets become "- ", removes inline emphasis.
  let s = md_src
  s = s.replace(/```([\s\S]*?)```/g, (_m, code) => code)         // code fences → bare code
  s = s.replace(/`([^`]+)`/g, '$1')                              // inline code
  s = s.replace(/\*\*([^*]+)\*\*/g, '$1').replace(/\*([^*]+)\*/g, '$1')
  s = s.replace(/__([^_]+)__/g, '$1').replace(/_([^_]+)_/g, '$1')
  s = s.replace(/^#{1,6}\s+/gm, '')                              // headings
  s = s.replace(/^\s*[-*+]\s+/gm, '• ')                          // bullets
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1 ($2)')           // links
  return s
}

async function copyAnswer(m: any) {
  const text = m.content_json?.text || ''
  if (!text) return
  const html = md.render(text)
  const plain = plainTextFromMarkdown(text)
  try {
    if (typeof (window as any).ClipboardItem === 'function' && navigator.clipboard?.write) {
      const item = new ClipboardItem({
        'text/html': new Blob([html], { type: 'text/html' }),
        'text/plain': new Blob([plain], { type: 'text/plain' }),
      })
      await navigator.clipboard.write([item])
    } else {
      await navigator.clipboard.writeText(plain)
    }
    ElMessage.success('已复制')
  } catch {
    // last-resort fallback for older browsers / non-HTTPS dev hosts
    try {
      const ta = document.createElement('textarea')
      ta.value = plain
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      ta.remove()
      ElMessage.success('已复制')
    } catch {
      ElMessage.error('复制失败')
    }
  }
}

function isFavorited(m: any): boolean {
  return space.isFavorited(m?.id)
}

async function toggleFavorite(m: any) {
  if (!m?.id) {
    ElMessage.warning('该消息还未保存,稍后再试')
    return
  }
  if (isFavorited(m)) {
    try {
      await ElMessageBox.confirm('确定取消收藏吗?', '确认', { type: 'warning' })
    } catch { return }
    try {
      await space.unfavorite(m.id)
      ElMessage.success('已取消收藏')
    } catch (e: any) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  } else {
    try {
      await space.favorite(m.id)
      ElMessage.success('已加入空间')
    } catch (e: any) {
      ElMessage.error(e?.response?.data?.detail || '操作失败')
    }
  }
}

let scrollBottomRaf = 0
async function scrollBottom() {
  await nextTick()
  if (scrollBottomRaf) return
  scrollBottomRaf = requestAnimationFrame(() => {
    scrollBottomRaf = 0
    const el = scrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function send() {
  if (!chat.currentAgent || !input.value.trim()) return
  // Per-send file count cap (Agent policy)
  const policy = chat.currentAgent?.upload_policy_json || {}
  const maxPerSend = Number(policy.max_files_per_send || 0)
  if (maxPerSend > 0 && chat.pendingFiles.length > maxPerSend) {
    ElMessage.warning(`单次发送最多 ${maxPerSend} 个文件,请删减后再发送`)
    return
  }
  // Block send while files are still parsing
  const stillParsing = chat.pendingFiles.filter((f: any) => f.parse_status === 'parsing')
  if (stillParsing.length) {
    ElMessage.warning(`还有 ${stillParsing.length} 个文件解析中,请稍候`)
    return
  }
  const isFirstMessage = chat.messages.length === 0
  // "@专家" dispatch: if a mentioned expert differs from the active one, switch
  // to it first so the new conversation is created bound to that expert. The
  // task text then flows to that expert's agent on send.
  if (mentionedExpert.value && mentionedExpert.value.id !== chat.currentAgent?.id) {
    chat.selectAgent(mentionedExpert.value)
  }
  if (!chat.currentConvId) {
    // Bind to the active workspace (if any) so this becomes a "task".
    await chat.ensureConv(ws.currentId, {
      model_id: selectedModelId.value,
      permission_mode: permissionMode.value,
    })
  } else if (ws.currentId != null) {
    // Conversation already exists but a workspace was (re)selected afterwards —
    // make sure the conversation is bound to it so file tools get injected.
    const c = chat.convs.find((x: any) => x.id === chat.currentConvId)
    if (c && c.workspace_id !== ws.currentId) {
      try {
        await api.bindConversationWorkspace(chat.currentConvId, ws.currentId)
        c.workspace_id = ws.currentId
        c.kind = 'task'
      } catch {}
    }
  }
  const text = input.value.trim()
  const fileIds = chat.pendingFiles.map((f) => f.id)
  // Snapshot file briefs onto the user message for history rendering
  const fileBriefs = chat.pendingFiles.map((f: any) => ({
    id: f.id, name: f.name, size: f.size, parse_status: f.parse_status, parsed_chars: f.parsed_chars,
  }))
  chat.messages.push({ _tmp: Date.now(), role: 'user', content_json: { text, files: fileBriefs } })
  chat.messages.push({
    _tmp: Date.now() + 1, role: 'assistant',
    content_json: { text: '' }, tool_calls_json: null,
    _meta: null, _thinking: '', _steps: [], _stepIndex: {} as Record<string, number>, _files: [], _uis: [],
    _streaming: true,
  })
  // IMPORTANT: keep a reference to the *reactive proxy* (last array element),
  // not the plain object literal above. Mutating the proxy is what notifies Vue.
  const placeholder: any = chat.messages[chat.messages.length - 1]
  input.value = ''
  mentionedExpert.value = null
  chat.pendingFiles = []
  await scrollBottom()

  // Bind the turn to the conversation it started in (not whatever's active when
  // it ends — the user may switch conversations mid-stream). The fetch loop runs
  // in the store (singleton), so the turn survives this view being unmounted.
  const cid = chat.currentConvId as number
  const body = {
    content: text,
    file_ids: fileIds,
    cli_app_ids: connectedApps.value.map((a) => a.id),
    skill_ids: selectedSkills.value.map((s) => s.id),
  }
  await chat.streamTurn(cid, body, placeholder)

  if (isFirstMessage && cid) {
    const conv = chat.convs.find((c) => c.id === cid)
    if (conv) {
      const title = text.replace(/\s+/g, ' ').trim().slice(0, 30)
      if (title && title !== conv.title) {
        chat.renameConv(conv, title).catch(() => {})
      }
    }
  }
}

// All still-pending approval requests across the whole conversation. Surfaced
// in a floating panel pinned above the messages so a blocked tool execution is
// always visible and confirmable without scrolling — once answered the request
// leaves this list and remains in the message stream as collapsed history.
const pendingPerms = computed(() => {
  const out: any[] = []
  for (const m of chat.messages as any[]) {
    if (!Array.isArray(m._perms)) continue
    for (const req of m._perms) {
      if (req.status === 'pending') out.push(req)
    }
  }
  return out
})

// Answer a pending tool-approval request. Posts the decision (which unblocks
// the agent turn server-side) and marks the card resolved.
async function answerPermission(
  req: any,
  behavior: 'allow' | 'deny',
  scope: 'once' | 'session' = 'once',
) {
  if (!req || req.status !== 'pending') return
  if (!chat.currentConvId) return
  req._busy = true
  try {
    await api.decidePermission(chat.currentConvId, req.request_id, { behavior, scope })
    req.status = behavior === 'allow' ? (scope === 'session' ? 'allowed-session' : 'allowed') : 'denied'
    // Collapse the card after a decision so it stops taking up space; the user
    // can click the header to expand the details again.
    req._collapsed = true
  } catch (e: any) {
    // 409 = request already expired (e.g. turn aborted). Mark stale.
    req.status = 'expired'
    req._collapsed = true
    ElMessage.warning(e?.response?.status === 409 ? '该授权请求已失效' : '提交失败')
  } finally {
    req._busy = false
  }
}

// Header status icon for a permission card (resolved → status, pending → tool).
function permStatusIcon(req: any) {
  switch (req.status) {
    case 'allowed':
    case 'allowed-session':
      return 'Select'
    case 'denied':
      return 'CloseBold'
    case 'expired':
      return 'Remove'
    default:
      return 'Lock'
  }
}

// Header text: collapsed-friendly summary once resolved, prompt while pending.
function permHeadText(req: any): string {
  switch (req.status) {
    case 'allowed':
      return '已允许本次'
    case 'allowed-session':
      return `本会话已放行 ${req.tool_name}`
    case 'denied':
      return '已拒绝'
    case 'expired':
      return '请求已失效'
    default:
      return req.risk === 'high' ? '高风险操作，需要确认' : '请求执行权限'
  }
}

</script>

<style scoped>
.chat-wrap {
  display: flex;
  height: 100%;
  background: #ffffff;
}
.chat-wrap.split-mode .conv { flex: 1 1 50%; max-width: 50%; }
.chat-wrap.split-mode :deep(.preview-panel) { flex: 1 1 50%; max-width: 50%; }

.files-block { display: flex; flex-direction: column; gap: 4px; }

/* Permission approval cards */
.perm-block { display: flex; flex-direction: column; gap: 8px; margin: 8px 0 10px; }
.perm-card {
  border: 0;
  border-radius: 15px;
  background: rgba(255, 255, 255, .98);
  font-size: 13px;
  overflow: hidden;
  box-shadow: 0 14px 36px rgba(0, 0, 0, .08), 0 1px 0 rgba(255, 255, 255, .9) inset;
  backdrop-filter: blur(18px) saturate(1.08);
  -webkit-backdrop-filter: blur(18px) saturate(1.08);
  transition: border-color .15s ease, box-shadow .15s ease, opacity .15s ease;
}
.perm-card.resolved {
  box-shadow: none;
  background: rgba(250, 250, 248, .88);
}
.perm-head {
  display: flex; align-items: center; gap: 8px;
  min-height: 36px;
  font-weight: 650; color: #242421;
  padding: 12px 14px 6px;
}
.perm-head.clickable { cursor: pointer; }
.perm-head.clickable:hover { background: rgba(28, 28, 26, .035); }
.perm-icon {
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: 999px;
  background: #f1f1ef;
  color: #56554e;
  font-size: 14px;
}
.perm-card:not(.resolved) .perm-icon {
  background: #fff7ed;
  color: #b45309;
}
.perm-title {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.perm-tool {
  max-width: 180px;
  font-family: var(--m-font-mono, monospace);
  font-size: 11px;
  line-height: 20px;
  padding: 0 7px;
  border-radius: 999px;
  background: #f1f1ef;
  color: #676761;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.perm-caret { margin-left: 2px; font-size: 13px; color: #aaa9a2; }
.perm-body { padding: 0 12px 12px 44px; }
.perm-reason {
  color: #676761;
  line-height: 1.55;
}
.perm-summary {
  margin: 8px 0 0;
  padding: 9px 10px;
  border-radius: 10px;
  background: #f6f6f3;
  border: 0;
  font-family: var(--m-font-mono, monospace);
  color: #3f3f3b;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 156px;
  overflow: auto;
}
.perm-actions { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 11px; }
.perm-btn {
  height: 28px;
  border: 0;
  border-radius: 8px;
  padding: 0 11px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  background: #f1f1ef;
  color: #3f3f3b;
  transition: opacity 0.15s, background 0.15s, transform 0.12s;
}
.perm-btn:hover:not(:disabled) { background: #e8e8e5; }
.perm-btn:active:not(:disabled) { transform: scale(.98); }
.perm-btn:disabled { opacity: 0.5; cursor: default; }
.perm-btn.allow { background: #242421; color: #fff; }
.perm-btn.allow:hover:not(:disabled) { background: #3a3a36; }
.perm-btn.allow-session { background: #ececea; color: #242421; }
.perm-btn.deny { background: transparent; color: #c2410c; }
.perm-btn.deny:hover:not(:disabled) { background: #fff7ed; }

/* Approval panel — sits directly above the input box inside .composer-wrap,
   so it shares the composer width and a blocked tool execution is always
   visible & confirmable right where the user is typing. */
.perm-float {
  width: 100%;
  max-height: 46vh;
  margin-bottom: 10px;
  display: flex;
  flex-direction: column;
  border: 0;
  border-radius: 17px;
  background: rgba(255, 255, 255, .58);
  box-shadow: 0 16px 42px rgba(0, 0, 0, .09);
  backdrop-filter: blur(22px) saturate(1.12);
  -webkit-backdrop-filter: blur(22px) saturate(1.12);
  overflow: hidden;
  box-sizing: border-box;
}
.perm-float-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 13px 6px;
  font-size: 12.5px;
  font-weight: 650;
  color: #242421;
}
.perm-float-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #d97706;
  flex-shrink: 0;
  box-shadow: 0 0 0 0 rgba(217, 119, 6, .5);
  animation: perm-pulse 1.8s ease-out infinite;
}
@keyframes perm-pulse {
  0% { box-shadow: 0 0 0 0 rgba(217, 119, 6, .45); }
  70% { box-shadow: 0 0 0 7px rgba(217, 119, 6, 0); }
  100% { box-shadow: 0 0 0 0 rgba(217, 119, 6, 0); }
}
.perm-float-label { flex: 1 1 auto; min-width: 0; }
.perm-float-count {
  font-size: 11px;
  font-weight: 500;
  color: #b45309;
  background: #fff7ed;
  border-radius: 999px;
  padding: 1px 9px;
  flex-shrink: 0;
}
.perm-float-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
  overflow-y: auto;
}
.perm-float .perm-card {
  box-shadow: 0 10px 26px rgba(0, 0, 0, .06);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  background: rgba(255, 255, 255, .98);
}
.perm-float .perm-card.is-high {
  background: #fffaf2;
}
.perm-float-enter-active,
.perm-float-leave-active { transition: opacity .22s ease, transform .22s ease; }
.perm-float-enter-from,
.perm-float-leave-to { opacity: 0; transform: translateY(10px); }

/* Conv main */
.conv { flex: 1; display: flex; flex-direction: column; min-width: 0; background: transparent; position: relative; }
.messages { flex: 1; overflow: auto; padding: 24px 35px 16px 30px; scroll-behavior: smooth; }

.welcome {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  height: 100%; color: var(--m-text-secondary); text-align: center;
  padding: 0 24px;
}
.welcome h2 {
  margin: 18px 0 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  font-weight: 760;
  font-size: 28px;
  line-height: 1.16;
  letter-spacing: 0;
  color: #20201e;
}
.welcome h2 span,
.welcome h2 strong { font: inherit; }
.welcome p { margin: 0; font-size: 13px; }
.welcome-intro { max-width: 620px; color: var(--m-text-secondary); line-height: 1.6; }
.welcome-starters {
  margin-top: 28px;
  display: flex; flex-direction: row; flex-wrap: wrap; gap: 10px;
  align-items: center;
  justify-content: center;
  width: 100%; max-width: 760px;
}
.starter-chip {
  appearance: none;
  width: auto;
  text-align: center;
  font-size: 13px; line-height: 1.5;
  padding: 7px 13px;
  border: 0;
  border-radius: 10px;
  background: #f1f1ef;
  color: var(--m-text);
  cursor: pointer;
  transition: background .12s, border-color .12s;
}
.starter-chip:hover:not(:disabled) {
  background: #e7e7e4;
}
.starter-chip:active:not(:disabled) { transform: scale(.99); }
.starter-chip:disabled { opacity: .55; cursor: not-allowed; }
.welcome-mark {
  display:grid; grid-template-columns: 1fr 1fr; gap: 4px; width: 40px; height: 40px;
  transform-origin: 50% 50%;
  animation: welcome-mark-drift 5.4s ease-in-out infinite;
}
.welcome-mark .dot {
  border-radius: 6px; width: 100%; height: 100%; box-shadow: inset 0 1px 0 rgba(255,255,255,.25);
  animation: welcome-mark-tone 5.4s ease-in-out infinite;
}
.welcome-mark .dot-1 { background:#2b2b2b } .welcome-mark .dot-2 { background:#56554e }
.welcome-mark .dot-3 { background:#8a897f } .welcome-mark .dot-4 { background:#b6b5ac }
@keyframes welcome-mark-drift {
  0%, 78%, 100% { transform: rotate(0deg) scale(1); }
  84% { transform: rotate(7deg) scale(1.04); }
  90% { transform: rotate(-5deg) scale(.99); }
  95% { transform: rotate(2deg) scale(1.02); }
}
@keyframes welcome-mark-tone {
  0%, 72%, 100% { filter: brightness(1); transform: translate(0,0); }
  80% { filter: brightness(1.14); transform: translateY(-1px); }
  88% { filter: brightness(.92); }
}

/* ── Home (command-center) mode ── */
/* When there is no active conversation, hide the (empty) scroll area and
   float a large centered composer in the middle of the screen. */
.chat-wrap.home-mode .conv { justify-content: center; }
.chat-wrap.home-mode .messages {
  flex: 0 0 auto; padding: 0; overflow: visible;
}
.chat-wrap.home-mode .welcome { height: auto; padding-bottom: 8px; }
.chat-wrap.home-mode .composer-wrap {
  max-width: 792px; padding: 14px 24px 12vh;
}
.chat-wrap.home-mode .composer {
  border: 1px solid #e9e9e6;
  box-shadow: 0 18px 42px -30px rgba(0,0,0,.20);
  gap: 10px;
  padding: 12px;
  overflow: visible;
}
.chat-wrap.home-mode .composer::before {
  content: "";
  position: absolute;
  inset: -1px;
  border-radius: 20px;
  background: #ffffff;
  border: 1px solid #e9e9e6;
  z-index: 1;
  pointer-events: none;
}
.chat-wrap.home-mode .composer :deep(.el-textarea__inner) { min-height: 70px !important; font-size: 14px; }

.msg { display: flex; gap: 12px; max-width: 910px; margin: 0 auto 18px; padding: 0 8px;transform: translateX(-20px); }
.msg.user { flex-direction: row-reverse; }
.avatar.bot {
  width: 30px; height: 30px; flex-shrink: 0;
  background: var(--m-surface); border: 1px solid var(--m-border);
  border-radius: 10px; padding: 6px;
  display:grid; grid-template-columns: 1fr 1fr; gap: 2px; box-sizing: border-box;
}
.avatar.bot .dot { border-radius: 50%; }
.avatar.bot .dot-1 { background:#2b2b2b } .avatar.bot .dot-2 { background:#56554e }
.avatar.bot .dot-3 { background:#8a897f } .avatar.bot .dot-4 { background:#b6b5ac }

/* Waiting state: avatar pulses, dots cycle */
.avatar.bot.is-thinking {
  border-color: var(--m-primary);
  box-shadow: 0 0 0 0 var(--m-primary-soft);
  animation: avatar-glow 1.6s ease-in-out infinite;
}
.avatar.bot.is-thinking .dot { animation: dot-pulse 1.2s ease-in-out infinite; }
.avatar.bot.is-thinking .dot-1 { animation-delay: 0s; }
.avatar.bot.is-thinking .dot-2 { animation-delay: .15s; }
.avatar.bot.is-thinking .dot-3 { animation-delay: .45s; }
.avatar.bot.is-thinking .dot-4 { animation-delay: .3s; }
@keyframes dot-pulse {
  0%, 100% { transform: scale(0.85); opacity: .55; }
  50%      { transform: scale(1.15); opacity: 1; }
}
@keyframes avatar-glow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(66,133,244,.18); }
  50%      { box-shadow: 0 0 0 4px rgba(66,133,244,.06); }
}

/* Thinking pill — shown next to avatar until first content arrives */
.thinking-pill {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 7px 12px;
  background: var(--m-surface-sunken);
  border: 0;
  border-radius: var(--m-radius);
  font-size: 13px; color: var(--m-text-secondary);
  align-self: flex-start;
  width: fit-content;
}
.thinking-text { font-weight: 500; }
.thinking-dots { display: inline-flex; gap: 3px; }
.thinking-dots span {
  width: 5px; height: 5px; border-radius: 50%;
  background: currentColor;
  animation: dot-bounce 1.2s ease-in-out infinite;
}
.thinking-dots span:nth-child(2) { animation-delay: .15s; }
.thinking-dots span:nth-child(3) { animation-delay: .3s; }
@keyframes dot-bounce {
  0%, 80%, 100% { opacity: .3; transform: translateY(0); }
  40%           { opacity: 1; transform: translateY(-3px); }
}
.thinking-tail {
  align-self: flex-start;
  min-height: 22px;
  padding: 0 4px;
  display: inline-flex;
  align-items: center;
  color: #aaa9a2;
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0;
}
.thinking-tail span {
  animation: thinking-tail-tone 1.8s ease-in-out infinite;
}
@keyframes thinking-tail-tone {
  0%, 100% { color: #b9b8b1; opacity: .58; }
  50% { color: #777770; opacity: .92; }
}

.bubble {
  max-width: 100%; padding: 8px;
  background: transparent; border: 1px solid transparent;
  border-radius: var(--m-radius-lg);
  font-size: 14px; line-height: 1.72; word-break: break-word;
}

/* "Jump back" highlight from /chat?msg=<id> */
.msg.is-highlighted .bubble {
  animation: msg-flash 1.6s ease-out;
}
@keyframes msg-flash {
  0%   { box-shadow: 0 0 0 0 var(--m-primary-soft); background: var(--m-primary-soft); }
  60%  { box-shadow: 0 0 0 6px transparent; background: var(--m-primary-soft); }
  100% { box-shadow: 0 0 0 0 transparent; background: var(--m-bg-soft); }
}

/* assistant message action bar — sits beneath the bubble */
.msg-actions {
  display: flex; align-items: center; gap: 4px;
  margin-top: 4px;
  padding: 0 4px;
  opacity: .5;
  transition: opacity .15s ease;
}
.msg:hover .msg-actions { opacity: 1; }
.msg-action {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 8px;
  font-size: 12px;
  color: var(--m-text-secondary);
  background: transparent;
  border: none;
  border-radius: var(--m-radius);
  cursor: pointer;
  transition: background .15s, color .15s;
}
.msg-action:hover { background: var(--m-surface-variant); color: var(--m-text); }
.msg-action.active { color: var(--m-primary); }
.msg-action.active:hover { background: var(--m-primary-soft); color: var(--m-primary-hover); }
.msg.user .bubble {
  background: #f1f1ef; color: #242421; border-color: transparent;
  box-shadow: none;
  border-radius: var(--m-radius-lg) var(--m-radius-sm) var(--m-radius-lg) var(--m-radius-lg);
}
.bubble--clamped { max-height: 200px; overflow: hidden; position: relative; }
.bubble-clamp-fade {
  position: absolute; bottom: 0; left: 0; right: 0; height: 56px;
  background: linear-gradient(to bottom, transparent, #f1f1ef);
  pointer-events: none;
  border-radius: 0 0 var(--m-radius-lg) var(--m-radius-sm);
}
.bubble-expand-btn {
  display: inline-flex; align-items: center; gap: 3px;
  align-self: flex-end;
  padding: 2px 8px; margin-top: 2px;
  font-size: 12px; color: var(--m-primary);
  background: transparent; border: none;
  cursor: pointer; opacity: .75;
  transition: opacity .15s;
}
.bubble-expand-btn:hover { opacity: 1; }
.bubble-expand-chevron { transition: transform .2s ease; }
.bubble-expand-chevron.rotated { transform: rotate(180deg); }
.msg.assistant .bubble { border-radius: var(--m-radius-sm) var(--m-radius-lg) var(--m-radius-lg) var(--m-radius-lg); }
.bubble-content {
  font-size: 14px;
  line-height: 1.72;
  color: var(--m-text);
}
.bubble :deep(p) { margin: 5px 0; font-size: inherit; line-height: inherit; }
.bubble :deep(p:first-child) { margin-top: 0; }
.bubble :deep(p:last-child) { margin-bottom: 0; }
.bubble :deep(strong),
.bubble :deep(b) {
  font-weight: 700;
}
.bubble :deep(em) {
  color: #56554e;
}
/* Unify heading sizes with body text — only weight distinguishes them. */
.bubble :deep(h1),
.bubble :deep(h2),
.bubble :deep(h3),
.bubble :deep(h4),
.bubble :deep(h5),
.bubble :deep(h6) {
  font-size: 14px;
  line-height: 1.72;
  font-weight: 700;
  margin: 12px 0 4px;
  color: var(--m-text);
}
.bubble :deep(h1:first-child),
.bubble :deep(h2:first-child),
.bubble :deep(h3:first-child),
.bubble :deep(h4:first-child),
.bubble :deep(h5:first-child),
.bubble :deep(h6:first-child) { margin-top: 0; }
.bubble :deep(ul),
.bubble :deep(ol) {
  margin: 6px 0;
  padding-left: 1.35em;
  font-size: inherit;
  line-height: inherit;
}
.bubble :deep(li) {
  margin: 3px 0;
  padding-left: 0;
  font-size: inherit;
  line-height: inherit;
}
.bubble :deep(li > p) {
  margin: 2px 0;
}
.bubble :deep(blockquote) {
  margin: 8px 0;
  padding: 2px 0 2px 14px;
  border: 0;
  color: #56554e;
  font-size: inherit;
  line-height: inherit;
}
.bubble :deep(hr) {
  height: 0;
  margin: 10px 0;
  border: 0;
}
.bubble :deep(table) {
  display: block;
  width: 100%;
  max-width: 100%;
  margin: 10px 0;
  border: 0;
  border-collapse: separate;
  border-spacing: 0;
  overflow-x: auto;
  font-size: 14px;
  line-height: 1.58;
}
.bubble :deep(thead) {
  background: transparent;
}
.bubble :deep(th),
.bubble :deep(td) {
  min-width: 72px;
  padding: 8px 10px;
  border: 0;
  text-align: left;
  vertical-align: top;
  font-size: inherit;
  line-height: inherit;
}
.bubble :deep(th) {
  background: #f1f1ef;
  color: #56554e;
  font-weight: 700;
}
.bubble :deep(th:first-child) {
  border-radius: 8px 0 0 8px;
}
.bubble :deep(th:last-child) {
  border-radius: 0 8px 8px 0;
}
.bubble :deep(tbody tr:nth-child(even) td) {
  background: #fafaf8;
}
.bubble :deep(tbody tr:hover td) {
  background: #f6f6f3;
}
.bubble :deep(.code-shell) {
  position: relative;
  margin: 12px 0;
  border-radius: 14px;
  background: #f7f7f5;
  overflow: hidden;
}
.bubble :deep(.code-tools) {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px;
  border-radius: 9px;
  background: rgba(255,255,255,.78);
  backdrop-filter: blur(10px);
  opacity: .68;
  transition: opacity .14s ease, background .14s ease;
}
.bubble :deep(.code-shell:hover .code-tools) {
  opacity: 1;
  background: rgba(255,255,255,.92);
}
.bubble :deep(.code-lang) {
  padding: 0 5px;
  color: #aaa9a2;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .04em;
  line-height: 22px;
}
.bubble :deep(.code-action) {
  height: 22px;
  padding: 0 7px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: #676761;
  font-size: 12px;
  cursor: pointer;
}
.bubble :deep(.code-action:hover) {
  background: #eeeeeb;
  color: #242421;
}
.bubble :deep(pre) {
  background: #f7f7f5;
  color: #3f3f3b;
  padding: 40px 16px 14px;
  border-radius: 14px;
  border: 0;
  overflow: auto;
  max-height: 420px;
  font-size: 13px;
  line-height: 1.55;
  margin: 12px 0;
  font-family: 'Roboto Mono', ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace;
  scrollbar-width: thin;
  scrollbar-color: #c4c7c5 transparent;
  position: relative;
}
.bubble :deep(pre)::-webkit-scrollbar { width: 8px; height: 8px; }
.bubble :deep(pre)::-webkit-scrollbar-track { background: transparent; }
.bubble :deep(pre)::-webkit-scrollbar-thumb { background: #dadce0; border-radius: 4px; }
.bubble :deep(pre)::-webkit-scrollbar-thumb:hover { background: #bdc1c6; }
.bubble :deep(pre code) { background: transparent; color: inherit; padding: 0; font-size: inherit; }
.bubble :deep(code) { font-family: 'Roboto Mono', ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace; }
.bubble :deep(:not(pre) > code) {
  background: #eeeeeb;
  color: #56554e;
  padding: 2px 6px;
  border-radius: 5px;
  font-size: inherit;
  border: 0;
}
.bubble :deep(.smart-link) {
  display: inline;
  max-width: none;
  vertical-align: baseline;
  padding: 0;
  border-radius: 0;
  background: transparent;
  color: #2563eb;
  text-decoration: none;
  text-underline-offset: 3px;
  overflow-wrap: anywhere;
  font-size: inherit;
}
.bubble :deep(.smart-link:hover) {
  color: #1d4ed8;
  text-decoration: underline;
}
.msg.user .bubble :deep(:not(pre) > code) { background: rgba(28,28,26,.08); color: #7b2d2a; }

.tool-trace-list { margin-top: 8px; }

/* Bubble stack: meta + thinking + steps + bubble vertically.
   `flex: 1` makes the stack always claim the available row space (capped by
   max-width), so widgets and tool cards render at a consistent width
   regardless of which child rendered first. */
.bubble-stack { display: flex; flex-direction: column; gap: 8px; flex: 1 1 auto; max-width: none; min-width: 0; }
.msg.user .bubble-stack { align-items: flex-end; max-width: 82%; }

.msg-meta {
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; color: var(--m-text-secondary);
  padding: 0 4px;
}
.msg-meta code { background: var(--m-surface-variant); padding: 1px 6px; border-radius: 4px; font-family: 'Roboto Mono', monospace; }
.dot-sep { color: var(--m-text-tertiary); }

.cap-info-btn {
  display: inline-flex; align-items: center; justify-content: center;
  border: none; background: transparent; cursor: pointer;
  margin-left: 8px; padding: 2px 4px; border-radius: 4px;
  color: var(--m-text-secondary); transition: background .15s, color .15s;
}
.cap-info-btn:hover { background: var(--m-surface-variant); color: var(--m-primary); }
.cap-info-btn-sm { margin-left: 4px; padding: 1px 3px; }

/* thinking card */
.thinking-card {
  border: 0;
  border-radius: var(--m-radius-lg);
  background: var(--m-surface-sunken);
  font-size: 13px;
}
.thinking-card summary {
  list-style: none; cursor: pointer;
  display: flex; align-items: center; gap: 6px;
  padding: 8px 12px; color: var(--m-text-secondary); font-weight: 500;
}
.thinking-card summary::-webkit-details-marker { display: none; }
.thinking-card[open] summary { border-bottom: 1px dashed var(--m-border); }
/* Wrapper: positions gradient overlay pseudo-elements */
.thinking-body {
  position: relative;
}
.thinking-body::before,
.thinking-body::after {
  content: '';
  position: absolute;
  left: 0; right: 0;
  height: 28px;
  pointer-events: none;
  z-index: 1;
}
.thinking-body::before {
  top: 0;
  background: linear-gradient(to bottom, #fafbfc 0%, transparent 100%);
}
.thinking-body::after {
  bottom: 0;
  background: linear-gradient(to top, #fafbfc 0%, transparent 100%);
}
.thinking-content {
  max-height: 200px;
  overflow-y: auto;
  padding: 10px 14px; white-space: pre-wrap; word-break: break-word;
  color: var(--m-text-secondary); line-height: 1.65; font-size: 13px;
  font-family: 'Inter', sans-serif;
  scrollbar-width: thin;
  scrollbar-color: var(--m-border-strong) transparent;
}
.thinking-content::-webkit-scrollbar { width: 4px; }
.thinking-content::-webkit-scrollbar-track { background: transparent; }
.thinking-content::-webkit-scrollbar-thumb {
  background: var(--m-border-strong);
  border-radius: 2px;
}

/* step cards (tool / mcp / skill calls) */
/* Execution-process panel */
.proc {
  margin: 2px 0 5px;
  color: #9a9a93;
}
.proc-head {
  display: flex; align-items: center; gap: 7px; width: fit-content;
  max-width: 100%;
  padding: 2px 4px; border: none; background: transparent; cursor: pointer;
  font-size: 12px; color: #9a9a93; text-align: left;
}
.proc-head:hover { color: #676761; }
.proc-spin { color: #9a9a93; }
.proc-ok { color: #77c593; }
.proc-title { font-weight: 600; color: #777770; }
.proc-count { color: #aaa9a2; font-size: 12px; }
.proc-caret { margin-left: 8px; color: #b7b7b1; transition: transform .15s; }
.proc-caret.open { transform: rotate(90deg); }
.proc-live {
  display: flex;
  align-items: center;
  gap: 7px;
  width: min(520px, 100%);
  min-height: 22px;
  margin: 2px 0 2px 4px;
  padding-left: 22px;
  color: #aaa9a2;
  font-size: 12px;
  overflow: hidden;
}
.proc-live-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #d9d9d4;
  flex-shrink: 0;
}
.proc-live.running .proc-live-dot {
  background: #9a9a93;
  animation: pulse 1.4s ease-in-out infinite;
}
.proc-live-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.step-list {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin: 4px 0 6px 8px;
  padding: 2px 0 2px 14px;
  border-left: 1px solid #ececea;
  max-height: 260px;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: #d2d2cd transparent;
}
.step-list::-webkit-scrollbar { width: 8px; height: 8px; }
.step-list::-webkit-scrollbar-track { background: transparent; }
.step-list::-webkit-scrollbar-thumb { background: #d2d2cd; border-radius: 6px; border: 2px solid transparent; background-clip: padding-box; }
.step-card {
  border: 0;
  border-radius: 0;
  background: transparent;
  padding: 0;
  font-size: 12px;
  color: #8a8a84;
  position: relative;
}
.step-card::before {
  content: "";
  position: absolute;
  left: -18px;
  top: 14px;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #d9d9d4;
}
.step-card.running::before {
  background: #aaa9a2;
  animation: pulse 1.4s ease-in-out infinite;
}
.step-card.done::before { background: #77c593; }
.step-head {
  display: flex; align-items: center; gap: 8px;
  padding: 5px 0;
  cursor: pointer;
  list-style: none;
  user-select: none;
  min-width: 0;
}
.step-head::-webkit-details-marker { display: none; }
.step-head:hover { color: #56554e; }
.step-head > .el-icon:first-child { flex-shrink: 0; }
.step-name { font-size: 12px; font-weight: 600; color: #777770; flex-shrink: 0; max-width: 210px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.step-summary {
  font-family: var(--m-font-mono); font-size: 11px;
  color: #aaa9a2; background: transparent;
  padding: 0;
  min-width: 0; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.step-server {
  font-size: 11px; color: #aaa9a2;
  background: transparent; padding: 0;
  flex-shrink: 0; font-style: italic;
}
.step-dur { font-size: 11px; flex-shrink: 0; color: #aaa9a2; }

.step-io-toggle {
  display: inline-flex; align-items: center; gap: 4px;
  margin-left: auto;
  color: #b7b7b1; font-size: 11px; font-weight: 500;
  flex-shrink: 0; white-space: nowrap; padding-left: 8px;
}
.step-chevron {
  color: #b7b7b1;
  transition: transform .2s ease;
}
.step-card[open] .step-chevron { transform: rotate(180deg); color: #777770; }

.step-body {
  padding: 3px 0 10px 24px;
  background: transparent;
}
.step-id-row { display: flex; align-items: center; gap: 8px; padding: 3px 0 4px; }
.step-raw-name { font-family: 'Roboto Mono', monospace; font-size: 11px; color: #aaa9a2; word-break: break-all; }
.step-block { margin-top: 8px; }
.step-block:first-child { margin-top: 0; }
.step-label { font-size: 10px; font-weight: 700; color: #aaa9a2; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 4px; }
.step-block pre {
  background: #f7f7f5; padding: 8px 10px; border-radius: 10px;
  font-family: 'Roboto Mono', monospace; font-size: 11px;
  color: #676761;
  margin: 0; max-height: 200px; overflow: auto; white-space: pre-wrap; word-break: break-word;
}

/* Composer */
.composer-wrap {
  padding: 10px 33px 20px 25px;
  max-width: 910px;
  width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
}

.files-row { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.files-row .el-tag :deep(.el-icon) { margin-right: 4px; vertical-align: -2px; }

/* Composer file chips with parse status */
.file-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 4px 6px 10px;
  background: var(--m-bg-soft);
  border: 0;
  border-radius: var(--m-radius);
  font-size: 12px;
  max-width: 280px;
  transition: border-color .2s, background .2s;
}
.file-chip.parsing { border-color: var(--m-primary); background: var(--m-primary-soft); }
.file-chip.done { border-color: transparent; background: var(--m-bg-soft); }
.file-chip.failed { border-color: var(--m-danger); background: #fce8e6; }

.file-chip .chip-leading { color: var(--m-text-secondary); flex-shrink: 0; }
.file-chip .chip-leading.ok { color: var(--m-success); }
.file-chip .chip-leading.err { color: var(--m-danger); }
.file-chip .spin { animation: spin 1s linear infinite; }

.file-chip .chip-name {
  font-weight: 500; color: var(--m-text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  max-width: 160px;
}
.file-chip .chip-meta {
  font-size: 11px; color: var(--m-text-secondary);
  flex-shrink: 0;
}
.file-chip .chip-action {
  background: transparent; border: none; cursor: pointer;
  font-size: 11px; color: var(--m-danger); font-weight: 500;
  padding: 0 4px;
}
.file-chip .chip-close {
  width: 20px; height: 20px; border-radius: 50%;
  border: none; background: transparent; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  color: var(--m-text-secondary);
  transition: background .15s, color .15s;
}
.file-chip .chip-close:hover { background: var(--m-surface-variant); color: var(--m-text); }

/* Inline file chips on user message bubbles */
.msg-files {
  display: flex; flex-wrap: wrap; gap: 4px;
  margin-bottom: 6px;
}
.msg-file-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 8px;
  background: rgba(255,255,255,.18);
  border-radius: var(--m-radius-pill);
  font-size: 11px;
}
.msg-file-chip.clickable { cursor: pointer; transition: background .15s; }
.msg-file-chip.clickable:hover { background: rgba(255,255,255,.32); }
.msg.assistant .msg-file-chip { background: var(--m-surface-variant); color: var(--m-text-secondary); }
.msg.assistant .msg-file-chip.clickable:hover { background: var(--m-primary-soft); color: var(--m-primary); }
.msg-file-meta { opacity: .7; }

.composer-shell {
  position: relative;
  z-index: 5;
  overflow: visible;
}

.composer {
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: #ffffff;
  backdrop-filter: blur(18px) saturate(1.2);
  -webkit-backdrop-filter: blur(18px) saturate(1.2);
  border: 1px solid #e9e9e6;
  border-radius: 20px;
  padding: 12px;
  transition: border-color .12s, box-shadow .12s;
  position: relative;
  isolation: isolate;
  box-shadow: 0 16px 38px -30px rgba(0,0,0,.28);
}
.composer-pet {
  position: absolute;
  right: 36px;
  top: -74px;
  z-index: 0;
}
.composer > :not(.composer-pet) {
  position: relative;
  z-index: 2;
}
/* Command palette popover (above input) */
.cmd-palette {
  position: absolute;
  left: 10px;
  right: 10px;
  bottom: calc(100% + 10px);
  box-sizing: border-box;
  background: rgba(255, 255, 255, .98);
  border: 1px solid rgba(28, 28, 26, .08);
  border-radius: 16px;
  box-shadow: 0 22px 54px rgba(0, 0, 0, .14), 0 1px 0 rgba(255, 255, 255, .9) inset;
  padding: 7px;
  z-index: 80;
  max-height: min(320px, 42vh);
  overflow: auto;
  overscroll-behavior: contain;
  backdrop-filter: blur(18px) saturate(1.1);
  -webkit-backdrop-filter: blur(18px) saturate(1.1);
}
.chat-wrap.home-mode .cmd-palette {
  max-height: min(300px, 34vh);
}
.cmd-hint { font-size: 11px; color: var(--m-text-tertiary, #9a9a93); padding: 4px 8px 6px; }
.cmd-group {
  font-size: 11px; font-weight: 650; letter-spacing: .04em;
  color: var(--m-text-tertiary, #9a9a93);
  padding: 8px 10px 4px;
}
.cmd-item {
  display: flex; align-items: center; gap: 9px;
  padding: 7px 10px; border-radius: var(--m-radius); cursor: pointer; font-size: 13px;
}
.cmd-item.active { background: var(--m-surface-variant, #f1f1ef); }
.cmd-ico { color: var(--m-text-secondary, #56554e); flex-shrink: 0; }
.cmd-name {
  font-family: var(--m-font-mono); font-size: 13px; color: var(--m-text);
  flex-shrink: 0; white-space: nowrap;
}
.cmd-desc {
  font-size: 12px; color: var(--m-text-tertiary, #9a9a93);
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.cmd-tag {
  flex-shrink: 0; font-size: 11px; color: var(--m-text-secondary);
  background: var(--m-surface-variant); border: 1px solid var(--m-border);
  padding: 1px 7px; border-radius: var(--m-radius-sm);
}

/* @-mention dispatch bar */
.mention-bar { padding: 2px 4px 6px; }
.mention-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 3px 6px 3px 9px; border-radius: var(--m-radius);
  font-size: 12px; font-weight: 500;
  background: var(--m-running-bg, #eef3f9); color: var(--m-running, #3a6fb0);
  border: 1px solid var(--m-running-bd, #c9dbef);
}
.mention-clear {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border: none; background: transparent; cursor: pointer;
  border-radius: var(--m-radius-sm); color: inherit; opacity: .7;
}
.mention-clear:hover { opacity: 1; background: rgba(0,0,0,.06); }

/* 专家生成器 chip — dark (black) background per design.
   The chip sits inline to the left of the textarea so the prefilled
   instruction text follows on the same line instead of wrapping below. */
.composer-input-row { display: flex; align-items: flex-start; gap: 8px; }
.composer-input-row.has-builder :deep(.el-textarea) { flex: 1; }
.builder-chip {
  display: inline-flex; align-items: center; gap: 6px; flex: none;
  margin-top: 5px; white-space: nowrap;
  padding: 3px 6px 3px 10px; border-radius: var(--m-radius);
  font-size: 12px; font-weight: 600;
  background: #1f1f1f; color: #fff;
  border: 1px solid #1f1f1f;
}
.builder-clear {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border: none; background: transparent; cursor: pointer;
  border-radius: var(--m-radius-sm); color: #fff; opacity: .65;
}
.builder-clear:hover { opacity: 1; background: rgba(255,255,255,.18); }
.cmd-ico { color: var(--m-text-secondary, #6b6b66); flex-shrink: 0; }
.cmd-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cmd-kind { font-size: 11px; color: var(--m-text-tertiary, #9a9a93); flex-shrink: 0; }
.composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 34px;
}
.composer-toolbar-left,
.composer-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.composer-toolbar-right { justify-content: flex-end; flex-shrink: 0; }
.composer-underbar {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  padding: 6px 0 0 16px;
}
.workspace-chip {
  background: transparent;
}
.workspace-chip.active {
  border-color: var(--m-border-strong);
  background: var(--m-surface-variant);
  color: var(--m-text);
}
.ws-name { max-width: 160px; overflow: hidden; text-overflow: ellipsis; }
.ws-path {
  font-size: 11px; color: var(--m-text-tertiary);
  max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ws-clear {
  display: inline-flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border: none; background: transparent; cursor: pointer;
  border-radius: var(--m-radius-sm); color: var(--m-text-tertiary);
}
.ws-clear:hover { background: var(--m-surface-variant); color: var(--m-danger); }
.model-chip {
  max-width: 230px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.model-chip.is-cli {
  cursor: default;
  opacity: 0.85;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}
.agent-chip {
  max-width: 200px;
  overflow: hidden;
  font-weight: 600;
  color: var(--m-text, #1c1c1a);
}
.agent-chip-avatar {
  width: 20px;
  height: 20px;
  border-radius: 7px;
  object-fit: cover;
  flex-shrink: 0;
}
.agent-chip-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.agent-select-option {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 180px;
  max-width: 260px;
}
.agent-select-avatar {
  width: 19px;
  height: 19px;
  border-radius: 6px;
  object-fit: cover;
  flex-shrink: 0;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .24);
}
.agent-select-name {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: var(--m-text, #1c1c1a);
}
.dd-hint { color: var(--m-text-tertiary); font-size: 11px; }
.tool-chip {
  display: inline-flex; align-items: center; gap: 5px;
  height: 30px;
  padding: 0 8px; border-radius: 8px;
  background: transparent; border: 1px solid transparent;
  font-size: 12px; color: #6f6f68; cursor: pointer;
  transition: background .14s, border-color .14s;
  white-space: nowrap;
}
.tool-chip:hover { background: var(--m-surface-variant, #ececea); border-color: transparent; color: var(--m-text, #1c1c1a); }
.tool-chip.active { color: var(--m-primary, #1a73e8); }
.permission-chip {
  max-width: 132px;
}
.apps-badge {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 15px; height: 15px; padding: 0 4px; margin-left: 2px;
  border-radius: 999px; background: var(--m-primary, #1a73e8); color: #fff;
  font-size: 10px; line-height: 1;
}
.apps-pop { max-height: 360px; display: flex; flex-direction: column; padding: 4px; }
.apps-pop-head { font-size: 12px; font-weight: 700; color: #777770; margin: 0 2px 6px; }
.apps-pop-empty { font-size: 12px; color: var(--m-text-tertiary, #9a9a93); padding: 8px 4px; line-height: 1.6; }
.apps-pop-list { overflow: auto; display: flex; flex-direction: column; gap: 2px; }
.apps-pop-item { display: flex; align-items: center; gap: 9px; padding: 6px 6px; border-radius: 9px; }
.apps-pop-item:hover { background: #eeeeeb; }
.apps-pop-icon {
  width: 28px; height: 28px; border-radius: 8px; background: #f1f1ef;
  display: flex; align-items: center; justify-content: center; color: #777770; flex-shrink: 0;
}
.apps-pop-main { flex: 1; min-width: 0; }
.apps-pop-name { font-size: 13px; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.apps-pop-sum { font-size: 11px; color: var(--m-text-tertiary, #9a9a93); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.apps-pop-btn {
  border: 0; background: #f1f1ef; color: #30302d; border-radius: 999px;
  height: 26px; padding: 0 12px; cursor: pointer; font-size: 12px; font-weight: 650; flex-shrink: 0;
}
.apps-pop-btn:hover:not(:disabled) { background: #e5e5e2; }
.apps-pop-btn:disabled { color: #b6b6b0; cursor: not-allowed; }
.apps-pop-btn.connected { background: #e6f4ea; color: #2f8f4e; }
.apps-pop-add {
  display: block; margin-top: 8px; padding: 8px 4px 2px; border-top: 1px solid var(--m-border, #ececea);
  font-size: 12px; font-weight: 600; color: var(--m-primary, #1a73e8); cursor: pointer; text-align: center;
}
.apps-pop-add:hover { text-decoration: underline; }
.wsfile-pop { max-height: 320px; overflow: auto; }
.wsfile-title { font-size: 12px; font-weight: 600; color: var(--m-text-secondary, #6b6b66); margin-bottom: 6px; }
.wsfile-empty { font-size: 12px; color: var(--m-text-tertiary, #9a9a93); padding: 8px; }
.wsfile-row { display: flex; align-items: center; gap: 7px; padding: 6px 8px; border-radius: 7px; cursor: pointer; font-size: 13px; }
.wsfile-row:hover { background: var(--m-surface-variant, #ececea); }
.wsfile-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.perm-opt { display: flex; flex-direction: column; line-height: 1.3; }
.perm-opt span { font-size: 11px; color: var(--m-text-tertiary, #9a9a93); }
:global(.apps-popover.el-popper),
:global(.agent-select-popper.el-popper),
:global(.perm-dropdown.el-popper) {
  border: 1px solid rgba(28,28,26,.08) !important;
  border-radius: 14px !important;
  background: rgba(255,255,255,.96) !important;
  box-shadow: 0 20px 50px -30px rgba(0,0,0,.36), 0 8px 18px -14px rgba(0,0,0,.20) !important;
  backdrop-filter: blur(18px) saturate(1.16);
  overflow: hidden;
}
:global(.apps-popover .el-popover__title),
:global(.agent-select-popper .el-popper__arrow),
:global(.perm-dropdown .el-popper__arrow),
:global(.apps-popover .el-popper__arrow) {
  display: none;
}
:global(.apps-popover.el-popover) {
  padding: 8px !important;
}
:global(.perm-dropdown .el-dropdown-menu) {
  padding: 6px !important;
  background: transparent !important;
  box-shadow: none !important;
}
:global(.perm-dropdown .el-dropdown-menu__item) {
  min-width: 230px;
  height: auto !important;
  line-height: 1.35 !important;
  padding: 7px 9px !important;
  border-radius: 9px !important;
}
:global(.perm-dropdown .el-dropdown-menu__item:not(.is-disabled):focus),
:global(.perm-dropdown .el-dropdown-menu__item:not(.is-disabled):hover) {
  background: #eeeeeb !important;
  color: #1f1f1d !important;
}
:global(.agent-select-menu.el-dropdown-menu) {
  padding: 6px !important;
  min-width: 218px;
  background: transparent !important;
  box-shadow: none !important;
}
:global(.agent-select-menu .el-dropdown-menu__item) {
  height: auto !important;
  min-height: 34px;
  padding: 6px 10px !important;
  border-radius: 10px !important;
  line-height: 1.2 !important;
}
:global(.agent-select-menu .el-dropdown-menu__item:not(.is-disabled):focus),
:global(.agent-select-menu .el-dropdown-menu__item:not(.is-disabled):hover) {
  background: var(--m-surface-variant, #f0f0ed) !important;
  color: var(--m-text, #1c1c1a) !important;
}
.composer:focus-within { box-shadow: 0 22px 58px -34px rgba(0,0,0,.4); }
.composer :deep(.el-textarea__inner) {
  border: none !important; background: transparent !important; box-shadow: none !important;
  padding: 4px 4px !important; min-height: 72px !important; resize: none; font-size: 14px;
}
.icon-btn, .send-btn {
  border: none; background: transparent; cursor: pointer;
  width: 34px; height: 34px; border-radius: 11px;
  display: flex; align-items: center; justify-content: center;
  color: var(--m-text-secondary); transition: background .12s ease;
}
.icon-btn.subtle {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  color: #777770;
}
.icon-btn:hover { background: var(--m-surface-variant); color: var(--m-text); }
.send-btn { background: #969691; color: #fff; box-shadow: none; border-radius: 999px; }
.send-btn:hover:not(:disabled) { background: var(--m-primary-hover); }
.send-btn:disabled { background: #c8c8c4; cursor: not-allowed; }
.stop-btn {
  border: none; cursor: pointer;
  width: 34px; height: 34px; border-radius: var(--m-radius);
  display: flex; align-items: center; justify-content: center;
  background: transparent; color: var(--m-text-secondary, #80868b);
  transition: background .15s ease, color .15s ease;
  flex-shrink: 0;
}
.stop-btn:hover { background: var(--m-surface-variant, #e8eaed); color: var(--m-text, #3c4043); }
.stop-btn:active { transform: scale(.93); }
.stop-spin { animation: spin 1s linear infinite; }

.is-loading { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
