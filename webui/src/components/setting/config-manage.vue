<script lang="ts" setup>
import type {
  BangumiManage,
  RenameMethod,
  RevisionConflictPolicy,
} from '#/config';
import type { SelectItem, SettingItem } from '#/components';

const { t } = useMyI18n();
const { getSettingGroup } = useConfigStore();

const manage = getSettingGroup('bangumi_manage');
const renameMethod: RenameMethod = [
  'normal',
  'pn',
  'advance',
  'custom',
  'none',
];
const revisionConflictPolicies: RevisionConflictPolicy = ['hold', 'replace'];

const customNamingFields = [
  ['title', 'config.manage_set.custom_help.field.title'],
  ['season', 'config.manage_set.custom_help.field.season'],
  ['episode', 'config.manage_set.custom_help.field.episode'],
  ['year', 'config.manage_set.custom_help.field.year'],
  ['group', 'config.manage_set.custom_help.field.group'],
  ['hash', 'config.manage_set.custom_help.field.hash'],
] as const;

const customNamingRules = [
  ['{title}', 'config.manage_set.custom_help.rule.direct'],
  ['{episode:02}', 'config.manage_set.custom_help.rule.zero_padding'],
  ['{year:[]}', 'config.manage_set.custom_help.rule.wrapper'],
  ['{group:()}', 'config.manage_set.custom_help.rule.wrapper_example'],
  ['{hash:[]}', 'config.manage_set.custom_help.rule.hash'],
  ['{episode:[]}', 'config.manage_set.custom_help.rule.missing'],
  ['{title:02}', 'config.manage_set.custom_help.rule.invalid_padding'],
  ['{episode:02[]}', 'config.manage_set.custom_help.rule.invalid_combination'],
  ['', 'config.manage_set.custom_help.rule.extension'],
  ['', 'config.manage_set.custom_help.rule.folder_fields'],
  ['', 'config.manage_set.custom_help.rule.revision'],
] as const;

const revisionConflictOptions = computed<SelectItem[]>(() => [
  {
    id: 1,
    label: t('config.manage_set.revision_conflict_hold'),
    value: revisionConflictPolicies[0],
  },
  {
    id: 2,
    label: t('config.manage_set.revision_conflict_replace'),
    value: revisionConflictPolicies[1],
  },
]);

const items = computed<SettingItem<BangumiManage>[]>(() => [
  {
    configKey: 'enable',
    label: () => t('config.manage_set.enable'),
    type: 'switch',
  },
  {
    configKey: 'rename_method',
    label: () => t('config.manage_set.method'),
    type: 'select',
    prop: {
      items: renameMethod,
    },
  },
  ...(manage.value.rename_method === 'custom'
    ? ([
        {
          configKey: 'custom_bangumi_folder',
          label: () => t('config.manage_set.custom_bangumi_folder'),
          type: 'input',
        },
        {
          configKey: 'custom_bangumi_file',
          label: () => t('config.manage_set.custom_bangumi_file'),
          type: 'input',
        },
        {
          configKey: 'custom_movie_folder',
          label: () => t('config.manage_set.custom_movie_folder'),
          type: 'input',
        },
        {
          configKey: 'custom_movie_file',
          label: () => t('config.manage_set.custom_movie_file'),
          type: 'input',
        },
      ] satisfies SettingItem<BangumiManage>[])
    : []),
  {
    configKey: 'revision_conflict_policy',
    label: () => t('config.manage_set.revision_conflict_policy'),
    description: t('config.manage_set.revision_conflict_hint'),
    type: 'select',
    prop: {
      items: revisionConflictOptions.value,
    },
    bottomLine: true,
  },
  {
    configKey: 'eps_complete',
    label: () => t('config.manage_set.eps'),
    type: 'switch',
  },
  {
    configKey: 'group_tag',
    label: () => t('config.manage_set.group_tag'),
    type: 'switch',
  },
  {
    configKey: 'remove_bad_torrent',
    label: () => t('config.manage_set.delete_bad_torrent'),
    type: 'switch',
  },
  {
    configKey: 'track_orphans',
    label: () => t('config.manage_set.track_orphans'),
    type: 'switch',
  },
]);
</script>

<template>
  <ab-fold-panel :title="$t('config.manage_set.title')">
    <div space-y-8>
      <template v-for="i in items" :key="i.configKey">
        <ab-setting v-bind="i" v-model:data="manage[i.configKey]"></ab-setting>

        <div
          v-if="
            i.configKey === 'rename_method' && manage.rename_method === 'custom'
          "
          class="custom-naming-heading"
        >
          <span>{{ $t('config.manage_set.custom_templates') }}</span>
          <ab-tooltip placement="bottom-start">
            <button
              type="button"
              class="custom-naming-help-button"
              :aria-label="$t('config.manage_set.custom_help_aria')"
              aria-haspopup="true"
            >
              ?
            </button>
            <template #content>
              <div class="custom-naming-help" role="note">
                <div class="custom-naming-help-line custom-naming-help-title">
                  {{ $t('config.manage_set.custom_help.fields_title') }}
                </div>
                <div
                  v-for="field in customNamingFields"
                  :key="field[0]"
                  class="custom-naming-help-line"
                >
                  <code>{{ field[0] }}</code> — {{ $t(field[1]) }}
                </div>
                <div class="custom-naming-help-line custom-naming-help-title">
                  {{ $t('config.manage_set.custom_help.syntax_title') }}
                </div>
                <div
                  v-for="(rule, index) in customNamingRules"
                  :key="index"
                  class="custom-naming-help-line"
                >
                  <code v-if="rule[0]">{{ rule[0] }}</code>
                  <span v-if="rule[0]"> — </span>{{ $t(rule[1]) }}
                </div>
              </div>
            </template>
          </ab-tooltip>
        </div>
      </template>
    </div>
  </ab-fold-panel>
</template>

<style lang="scss" scoped>
.custom-naming-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
}

.custom-naming-help-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: 50%;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;

  &:focus-visible {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
  }
}

.custom-naming-help {
  max-width: min(520px, calc(100vw - 32px));
  line-height: 1.45;
}

.custom-naming-help-line + .custom-naming-help-line {
  margin-top: 6px;
}

.custom-naming-help-title {
  margin-top: 10px;
  font-weight: 700;

  &:first-child {
    margin-top: 0;
  }
}

.custom-naming-help code {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  white-space: nowrap;
}
</style>
