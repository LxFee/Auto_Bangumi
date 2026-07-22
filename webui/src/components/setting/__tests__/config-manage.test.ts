import { mount } from '@vue/test-utils';
import { defineComponent, nextTick } from 'vue';
import ConfigManage from '../config-manage.vue';

vi.mock('@/hooks/useMyI18n', () => ({
  useMyI18n: () => ({ t: (key: string) => key }),
}));

vi.mock('@/store/config', async () => {
  const { computed, reactive } = await vi.importActual<typeof import('vue')>(
    'vue'
  );
  const manageState = reactive({
    enable: true,
    eps_complete: false,
    rename_method: 'pn',
    custom_bangumi_folder: '{title} {year:()}/Season {season}',
    custom_bangumi_file: '{title} S{season:02}E{episode:02}',
    custom_movie_folder: '{title} {year:()}',
    custom_movie_file: '{title} {year:()}',
    revision_conflict_policy: 'hold',
    group_tag: false,
    remove_bad_torrent: false,
    track_orphans: true,
  });
  return {
    __manageState: manageState,
    useConfigStore: () => ({
      getSettingGroup: () => computed(() => manageState),
    }),
  };
});

const AbSettingStub = defineComponent({
  name: 'AbSettingStub',
  props: {
    data: { type: [String, Boolean], default: undefined },
    description: { type: String, default: '' },
    label: { type: [String, Function], required: true },
    prop: { type: Object, default: undefined },
    type: { type: String, required: true },
  },
  emits: ['update:data'],
  template: '<div class="setting-stub"></div>',
});

describe('config-manage', () => {
  it('offers a safe hold default and an explicit higher-revision replacement', async () => {
    const wrapper = mount(ConfigManage, {
      global: {
        stubs: {
          'ab-fold-panel': { template: '<section><slot /></section>' },
          'ab-setting': AbSettingStub,
          'ab-tooltip': { template: '<div><slot /></div>' },
        },
      },
    });
    const settings = wrapper.findAllComponents(AbSettingStub);
    const policy = settings.find((setting) => {
      const label = setting.props('label') as () => string;
      return label() === 'config.manage_set.revision_conflict_policy';
    });

    expect(policy).toBeDefined();
    if (!policy) throw new Error('revision conflict policy setting not found');
    expect(policy.props('data')).toBe('hold');
    expect(policy.props('description')).toBe(
      'config.manage_set.revision_conflict_hint'
    );
    expect(policy.props('prop')?.items).toEqual([
      {
        id: 1,
        label: 'config.manage_set.revision_conflict_hold',
        value: 'hold',
      },
      {
        id: 2,
        label: 'config.manage_set.revision_conflict_replace',
        value: 'replace',
      },
    ]);

    await policy.vm.$emit('update:data', 'replace');
    await nextTick();
    const store = (await import('@/store/config')) as unknown as {
      __manageState: { revision_conflict_policy: string };
    };
    expect(store.__manageState.revision_conflict_policy).toBe('replace');
  });

  it('shows four custom templates and one formatted field help entry', async () => {
    const wrapper = mount(ConfigManage, {
      global: {
        stubs: {
          'ab-fold-panel': { template: '<section><slot /></section>' },
          'ab-setting': AbSettingStub,
          'ab-tooltip': {
            template:
              '<div class="tooltip-stub"><slot /><slot name="content" /></div>',
          },
        },
      },
    });
    const method = wrapper.findAllComponents(AbSettingStub).find((setting) => {
      const label = setting.props('label') as () => string;
      return label() === 'config.manage_set.method';
    });
    expect(method).toBeDefined();
    if (!method) throw new Error('rename method setting not found');

    await method.vm.$emit('update:data', 'custom');
    await nextTick();

    const labels = wrapper.findAllComponents(AbSettingStub).map((setting) => {
      const label = setting.props('label') as () => string;
      return label();
    });
    expect(labels).toEqual(
      expect.arrayContaining([
        'config.manage_set.custom_bangumi_folder',
        'config.manage_set.custom_bangumi_file',
        'config.manage_set.custom_movie_folder',
        'config.manage_set.custom_movie_file',
      ])
    );
    const helpButtons = wrapper.findAll('.custom-naming-help-button');
    expect(helpButtons).toHaveLength(1);
    expect(helpButtons[0].attributes('type')).toBe('button');
    expect(helpButtons[0].attributes('aria-label')).toBe(
      'config.manage_set.custom_help_aria'
    );

    const helpLines = wrapper
      .findAll('.custom-naming-help-line')
      .map((line) => line.text());
    expect(helpLines.some((line) => line.includes('title'))).toBe(true);
    expect(helpLines.some((line) => line.includes('episode'))).toBe(true);
    expect(
      helpLines.some((line) =>
        line.includes('config.manage_set.custom_help.fields_title')
      )
    ).toBe(true);
    expect(
      helpLines.some((line) =>
        line.includes('config.manage_set.custom_help.field.episode')
      )
    ).toBe(true);
    expect(helpLines.some((line) => line.includes('{episode:02}'))).toBe(true);
    expect(helpLines.some((line) => line.includes('{hash:[]}'))).toBe(true);
    expect(helpLines.some((line) => line.includes('{hash:【】}'))).toBe(false);
    expect(helpLines.some((line) => line.includes('{episode:02[]}'))).toBe(
      true
    );
  });
});
