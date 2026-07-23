<script lang="ts" setup>
import type {
  BangumiAPI,
  BangumiGroupDetail,
  BangumiRule,
  NamingPlan,
} from '#/bangumi';

const props = defineProps<{ groupId: number }>();
const detail = ref<BangumiGroupDetail | null>(null);
const selectedId = ref<number | null>(null);
const loading = ref(true);
const refreshing = ref(false);
const saving = ref(false);
const editingMetadata = ref(false);
const message = ref('');
const draft = reactive<Record<string, string | number | null>>({});
const metadataDraft = reactive({
  official_title: '',
  year: '' as string | null,
  season: 1,
  episode_type: 'episode' as 'episode' | 'movie' | 'special',
});
const associationDraft = reactive<Record<number, number | null>>({});

const videos = computed(() =>
  (detail.value?.plans ?? [])
    .filter((item) => item.file_kind === 'video')
    .slice()
    .sort((left, right) => {
      const leftEpisode = finalEpisode(left);
      const rightEpisode = finalEpisode(right);
      if (leftEpisode === null) return rightEpisode === null ? 0 : 1;
      if (rightEpisode === null) return -1;
      return leftEpisode - rightEpisode;
    })
);
const unassociatedSubtitles = computed(() =>
  (detail.value?.plans ?? []).filter(
    (item) => item.file_kind === 'subtitle' && item.subtitle_of_id === null
  )
);
const selected = computed(() =>
  videos.value.find((item) => item.id === selectedId.value)
);

function parseObject(value: string | null): Record<string, unknown> {
  if (!value) return {};
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === 'object'
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function fields(plan: NamingPlan): Record<string, unknown> {
  const manual = parseObject(plan.manual_fields);
  return {
    ...parseObject(plan.default_snapshot),
    ...Object.fromEntries(
      Object.entries(manual).filter(([key]) => !key.startsWith('_'))
    ),
  };
}

function requiredFields(plan: NamingPlan): string[] {
  try {
    const parsed: unknown = JSON.parse(plan.required_fields || '[]');
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

function editableFields(plan: NamingPlan): string[] {
  return requiredFields(plan).includes('episode') ? ['episode'] : [];
}

function sourceRule(plan: NamingPlan): BangumiAPI | undefined {
  return detail.value?.rules.find((item) => item.id === plan.rule_id);
}

function subtitles(plan: NamingPlan): NamingPlan[] {
  return (detail.value?.plans ?? []).filter(
    (item) => item.file_kind === 'subtitle' && item.subtitle_of_id === plan.id
  );
}

function status(plan: NamingPlan): '异常' | '手动' | '缺省' {
  if (plan.anomaly_reason) return '异常';
  const manual = parseObject(plan.manual_fields);
  return Object.keys(manual).some((key) => !key.startsWith('_'))
    ? '手动'
    : '缺省';
}

function parsedEpisode(plan: NamingPlan): number | null {
  const value = fields(plan).episode;
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value !== 'string' || value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function finalEpisode(plan: NamingPlan): number | null {
  const episode = parsedEpisode(plan);
  if (episode === null) return null;
  const offset = sourceRule(plan)?.episode_offset ?? 0;
  return episode + offset;
}

function effectiveEpisode(plan: NamingPlan): string {
  return String(finalEpisode(plan) ?? '—');
}

function select(plan: NamingPlan) {
  selectedId.value = selectedId.value === plan.id ? null : plan.id;
  Object.keys(draft).forEach((key) => delete draft[key]);
  for (const key of editableFields(plan)) {
    const value = fields(plan)[key];
    draft[key] =
      typeof value === 'string' || typeof value === 'number' ? value : null;
  }
}

function syncMetadataDraft() {
  if (!detail.value) return;
  Object.assign(metadataDraft, {
    official_title: detail.value.group.official_title,
    year: detail.value.group.year,
    season: detail.value.group.season,
    episode_type: detail.value.group.episode_type,
  });
}

function errorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } })
      .response;
    if (response?.data?.detail) return response.data.detail;
  }
  return '操作失败';
}

async function load(refresh = true) {
  loading.value = true;
  message.value = '';
  try {
    detail.value = refresh
      ? await apiBangumi.refreshGroup(props.groupId)
      : await apiBangumi.getGroup(props.groupId);
    syncMetadataDraft();
  } catch (error) {
    message.value = errorMessage(error);
    if (refresh) {
      detail.value = await apiBangumi.getGroup(props.groupId);
      syncMetadataDraft();
    }
  } finally {
    loading.value = false;
  }
}

async function refresh() {
  refreshing.value = true;
  try {
    await load(true);
    message.value = '文件列表已刷新';
  } finally {
    refreshing.value = false;
  }
}

async function save(apply: boolean) {
  if (!selected.value) return;
  saving.value = true;
  message.value = '';
  try {
    const patch = Object.fromEntries(
      editableFields(selected.value).map((key) => [key, draft[key]])
    );
    await apiBangumi.correctNamingPlan(selected.value.id, patch);
    if (apply) {
      const revision = await apiBangumi.applyNamingPlan(selected.value.id);
      message.value =
        revision.state === 'applied'
          ? '已应用重命名'
          : revision.last_error || '已保存，后台将继续重试';
    } else {
      message.value = '手动修改已保存';
    }
    await load(false);
  } catch (error) {
    message.value = errorMessage(error);
  } finally {
    saving.value = false;
  }
}

async function restore() {
  if (!selected.value) return;
  saving.value = true;
  try {
    await apiBangumi.restoreNamingPlan(selected.value.id);
    message.value = '已恢复缺省值，请确认预览后应用';
    await load(false);
  } catch (error) {
    message.value = errorMessage(error);
  } finally {
    saving.value = false;
  }
}

async function reparse() {
  if (!selected.value) return;
  saving.value = true;
  try {
    await apiBangumi.reparseNamingPlan(selected.value.id);
    message.value = '已重新解析缺省值，手动值保持不变';
    await load(false);
  } catch (error) {
    message.value = errorMessage(error);
  } finally {
    saving.value = false;
  }
}

async function saveMetadata() {
  saving.value = true;
  try {
    await apiBangumi.updateGroup(props.groupId, {
      ...metadataDraft,
      year: metadataDraft.year || null,
    });
    editingMetadata.value = false;
    message.value = '番剧信息已保存，目标名称预览已更新';
    await load(false);
  } catch (error) {
    message.value = errorMessage(error);
  } finally {
    saving.value = false;
  }
}

async function associate(subtitle: NamingPlan) {
  const videoId = associationDraft[subtitle.id];
  if (!videoId) return;
  saving.value = true;
  try {
    await apiBangumi.associateSubtitle(subtitle.id, videoId);
    message.value = '字幕关联已保存';
    await load(false);
  } catch (error) {
    message.value = errorMessage(error);
  } finally {
    saving.value = false;
  }
}

function editRule(rule: BangumiAPI) {
  const normalized: BangumiRule = {
    ...rule,
    filter: rule.filter.split(','),
    rss_link: rule.rss_link.split(','),
    air_weekday: rule.air_weekday ?? null,
  };
  useBangumiStore().openEditPopup(normalized);
}

onMounted(() => load(true));
watch(
  () => props.groupId,
  () => load(true)
);
</script>

<template>
  <div class="workbench">
    <header v-if="detail" class="heading">
      <div>
        <router-link to="/bangumi" class="back">← 返回番剧</router-link>
        <h1>{{ detail.group.official_title }}</h1>
        <p>
          {{ detail.group.year || '年份未知' }} · S{{ detail.group.season }} ·
          {{ detail.rules.length }} 条规则
        </p>
      </div>
      <div class="header-actions">
        <span v-if="detail.group.migration_review" class="review-badge">
          分组待确认
        </span>
        <button type="button" class="secondary" @click="editingMetadata = true">
          编辑番剧信息
        </button>
        <button
          type="button"
          class="secondary"
          :disabled="refreshing"
          @click="refresh"
        >
          {{ refreshing ? '刷新中…' : '刷新文件' }}
        </button>
      </div>
    </header>

    <section v-if="detail" class="rules">
      <span>来源规则</span>
      <button
        v-for="rule in detail.rules"
        :key="rule.id"
        type="button"
        class="rule-chip"
        @click="editRule(rule)"
      >
        {{ rule.group_name || rule.rule_name || `规则 ${rule.id}` }}
      </button>
    </section>

    <section v-if="editingMetadata" class="metadata-editor">
      <label
        ><span>title</span><input v-model="metadataDraft.official_title"
      /></label>
      <label
        ><span>year</span
        ><input v-model="metadataDraft.year" inputmode="numeric"
      /></label>
      <label
        ><span>season</span
        ><input v-model.number="metadataDraft.season" type="number" min="0"
      /></label>
      <label>
        <span>type</span>
        <select v-model="metadataDraft.episode_type">
          <option value="episode">episode</option>
          <option value="special">special</option>
          <option value="movie">movie</option>
        </select>
      </label>
      <div class="metadata-actions">
        <button
          type="button"
          class="secondary"
          @click="editingMetadata = false"
        >
          取消
        </button>
        <button
          type="button"
          class="primary"
          :disabled="saving"
          @click="saveMetadata"
        >
          保存
        </button>
      </div>
    </section>

    <div v-if="loading" class="empty">正在读取下载器文件列表…</div>
    <div v-else-if="!videos.length" class="empty">
      暂无可命名文件。下载器返回真实文件列表后会自动出现在这里。
    </div>
    <div v-else class="table-shell">
      <div class="table-head row-grid">
        <span>集</span><span>来源规则</span><span>字段来源</span
        ><span>目标名称</span><span></span>
      </div>
      <template v-for="plan in videos" :key="plan.id">
        <button type="button" class="plan-row row-grid" @click="select(plan)">
          <strong>E{{ effectiveEpisode(plan) }}</strong>
          <span>
            {{
              sourceRule(plan)?.group_name ||
              sourceRule(plan)?.rule_name ||
              '未命名规则'
            }}
          </span>
          <span
            class="badge"
            :class="{
              danger: plan.anomaly_reason,
              manual: status(plan) === '手动',
            }"
          >
            {{ status(plan) }}
          </span>
          <code :class="{ invalid: !plan.target_path }">
            {{ plan.target_path || plan.anomaly_reason }}
          </code>
          <span>{{ selectedId === plan.id ? '收起' : '编辑' }}</span>
        </button>

        <section v-if="selectedId === plan.id" class="editor">
          <div class="source-name">
            <small>当前文件</small><code>{{ plan.current_path }}</code>
          </div>
          <div class="field-grid">
            <label v-for="key in editableFields(plan)" :key="key">
              <span>{{ key }}</span>
              <input v-model.number="draft[key]" type="number" step="0.1" />
              <small>
                缺省：{{ parseObject(plan.default_snapshot)[key] ?? '未解析' }}
                <template v-if="sourceRule(plan)?.episode_offset">
                  ，offset：{{ sourceRule(plan)?.episode_offset }}，最终：{{
                    effectiveEpisode(plan)
                  }}
                </template>
              </small>
            </label>
          </div>
          <div v-if="subtitles(plan).length" class="subtitle-note">
            {{ subtitles(plan).length }} 个字幕将作为同一命名单元一起改名
          </div>
          <div v-if="plan.anomaly_reason" class="anomaly">
            {{ plan.anomaly_reason }}
          </div>
          <div class="actions">
            <button
              type="button"
              class="secondary"
              :disabled="saving"
              @click="reparse"
            >
              重新解析
            </button>
            <button
              type="button"
              class="secondary"
              :disabled="saving"
              @click="restore"
            >
              恢复缺省
            </button>
            <button
              type="button"
              class="secondary"
              :disabled="saving"
              @click="save(false)"
            >
              仅保存
            </button>
            <button
              type="button"
              class="primary"
              :disabled="saving"
              @click="save(true)"
            >
              应用重命名
            </button>
          </div>
        </section>
      </template>
    </div>

    <section v-if="unassociatedSubtitles.length" class="subtitle-anomalies">
      <h2>待关联字幕</h2>
      <p>这些字幕无法唯一匹配视频，请手动选择所属剧集。</p>
      <div
        v-for="subtitle in unassociatedSubtitles"
        :key="subtitle.id"
        class="subtitle-association"
      >
        <code>{{ subtitle.current_path }}</code>
        <select v-model="associationDraft[subtitle.id]">
          <option :value="null">选择视频</option>
          <option v-for="video in videos" :key="video.id" :value="video.id">
            E{{ effectiveEpisode(video) }} · {{ video.current_path }}
          </option>
        </select>
        <button
          type="button"
          class="secondary"
          :disabled="saving"
          @click="associate(subtitle)"
        >
          保存关联
        </button>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>
  </div>
</template>

<style lang="scss" scoped>
.workbench {
  flex: 1;
  min-height: 0;
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  color: var(--color-text);
}

.heading,
.header-actions,
.rules,
.actions,
.metadata-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.heading {
  flex-wrap: wrap;
  justify-content: space-between;
  margin-bottom: 18px;
}

.header-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
  margin-left: auto;
}

.heading h1 {
  margin: 8px 0 4px;
  font-size: 28px;
}

.heading p,
.back,
small,
.subtitle-anomalies p {
  color: var(--color-text-secondary);
}

.back {
  text-decoration: none;
}

.review-badge,
.badge {
  border-radius: 999px;
  padding: 4px 9px;
  background: var(--color-surface-hover);
  font-size: 12px;
}

.review-badge,
.badge.danger,
.anomaly {
  color: #c23b36;
  background: #fff0ef;
}

.badge.manual {
  color: var(--color-primary);
}

.rules {
  flex-wrap: wrap;
  margin-bottom: 18px;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.rule-chip {
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 5px 10px;
  color: var(--color-text);
  background: var(--color-surface);
  cursor: pointer;
}

.metadata-editor {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr auto;
  gap: 12px;
  align-items: end;
  margin-bottom: 18px;
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-hover);
}

.table-shell {
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}

.row-grid {
  display: grid;
  grid-template-columns: 70px 180px 90px minmax(280px, 1fr) 56px;
  gap: 14px;
  align-items: center;
}

.table-head {
  padding: 11px 16px;
  color: var(--color-text-secondary);
  background: var(--color-surface-hover);
  font-size: 12px;
}

.plan-row {
  width: 100%;
  padding: 15px 16px;
  border: 0;
  border-top: 1px solid var(--color-border);
  color: inherit;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.plan-row:hover {
  background: var(--color-surface-hover);
}

code {
  overflow: hidden;
  color: inherit;
  text-overflow: ellipsis;
  white-space: nowrap;
}

code.invalid {
  color: #c23b36;
}

.editor {
  padding: 20px 24px 22px 100px;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-hover);
}

.source-name,
label {
  display: grid;
  gap: 6px;
}

.source-name {
  margin-bottom: 16px;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 260px));
  gap: 14px;
}

label {
  font-size: 13px;
}

input,
select {
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid var(--color-border);
  border-radius: 7px;
  color: inherit;
  background: var(--color-surface);
}

.subtitle-note,
.anomaly {
  margin-top: 14px;
  padding: 10px 12px;
  border-radius: 7px;
}

.actions,
.metadata-actions {
  justify-content: flex-end;
  margin-top: 18px;
}

.metadata-actions {
  margin-top: 0;
}

button.secondary,
button.primary {
  padding: 8px 14px;
  border-radius: 7px;
  cursor: pointer;
}

.secondary {
  border: 1px solid var(--color-border);
  color: inherit;
  background: var(--color-surface);
}

.primary {
  border: 1px solid var(--color-primary);
  color: white;
  background: var(--color-primary);
}

button:disabled {
  cursor: wait;
  opacity: 0.55;
}

.subtitle-anomalies {
  margin-top: 20px;
  padding: 18px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.subtitle-anomalies h2 {
  margin: 0;
  font-size: 16px;
}

.subtitle-association {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) minmax(220px, 1fr) auto;
  gap: 10px;
  align-items: center;
  margin-top: 10px;
}

.empty {
  padding: 64px 24px;
  color: var(--color-text-secondary);
  text-align: center;
}

.message {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 20;
  max-width: min(480px, calc(100vw - 48px));
  padding: 10px 14px;
  border-radius: 8px;
  color: white;
  background: #28232f;
}

@media (max-width: 760px) {
  .workbench {
    padding: 16px;
  }

  .heading {
    flex-direction: column;
    align-items: flex-start;
  }

  .header-actions {
    width: 100%;
    margin-left: 0;
    flex-direction: column;
    align-items: stretch;
  }

  .table-head {
    display: none;
  }

  .row-grid {
    grid-template-columns: 48px 1fr 64px;
  }

  .plan-row code {
    grid-column: 2 / -1;
  }

  .plan-row > :last-child {
    display: none;
  }

  .editor {
    padding: 18px;
  }

  .metadata-editor,
  .subtitle-association {
    grid-template-columns: 1fr;
  }

  .actions {
    flex-wrap: wrap;
  }
}
</style>
