<script lang="ts" setup>
import EpisodeNamingWorkbench from '@/components/episode-naming-workbench.vue';
import AbTorrentListPage from '@/components/ab-torrent-list-page.vue';
import { apiBangumi } from '@/api/bangumi';

definePage({
  name: 'Bangumi Torrents',
});

const route = useRoute();
const router = useRouter();
const { t } = useI18n();

// KeepAlive 会复用同一实例，路由参数必须保持响应式；非法 id 归一为 null
const bangumiId = computed(() => {
  const id = Number((route.params as Record<string, string>).id);
  return Number.isInteger(id) && id > 0 ? id : null;
});

// 非法 id 不请求 API，直接回番剧列表（仅当当前仍在本页时，
// 避免 KeepAlive 缓存期间路由切换触发误跳转）
watch(
  bangumiId,
  (id) => {
    if (id === null && route.name === 'Bangumi Torrents') {
      router.replace('/bangumi');
    }
  },
  { immediate: true }
);

const showTorrentRecords = computed(() => route.query.view === 'torrents');
const pageProps = computed(() => {
  const id = bangumiId.value;
  if (id === null) return null;
  return {
    title: `${t('homepage.torrents.title')} #${id}`,
    loadFn: () => apiBangumi.getGroupTorrents(id),
    deleteOne: (torrentId: number) =>
      apiBangumi.deleteGroupTorrent(id, torrentId),
    deleteAll: () => apiBangumi.deleteGroupTorrents(id),
  };
});
</script>

<template>
  <AbTorrentListPage
    v-if="showTorrentRecords && pageProps"
    :key="`torrents-${bangumiId}`"
    v-bind="pageProps"
  />
  <EpisodeNamingWorkbench
    v-else-if="bangumiId"
    :key="bangumiId"
    :group-id="bangumiId"
  />
</template>
