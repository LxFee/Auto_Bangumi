import { mount } from '@vue/test-utils';
import { NTooltip } from 'naive-ui';
import { nextTick } from 'vue';
import AbTooltip from '../ab-tooltip.vue';

describe('ab-tooltip', () => {
  it('opens for hover, keyboard focus, and click and closes with Escape', async () => {
    const wrapper = mount(AbTooltip, {
      slots: {
        default: '<button type="button">Help</button>',
        content: '<span>Template help</span>',
      },
    });
    const trigger = wrapper.get('.ab-tooltip-trigger');
    const tooltip = wrapper.findComponent(NTooltip);

    await trigger.trigger('mouseenter');
    expect(tooltip.props('show')).toBe(true);
    await trigger.trigger('mouseleave');
    expect(tooltip.props('show')).toBe(false);

    await trigger.trigger('focusin');
    expect(tooltip.props('show')).toBe(true);
    await trigger.trigger('focusout');
    expect(tooltip.props('show')).toBe(false);

    await trigger.trigger('click');
    expect(tooltip.props('show')).toBe(true);
    await trigger.trigger('keydown', { key: 'Escape' });
    await nextTick();
    expect(tooltip.props('show')).toBe(false);

    await trigger.trigger('focusin');
    await trigger.trigger('click');
    await trigger.trigger('click');
    expect(tooltip.props('show')).toBe(false);
  });
});
