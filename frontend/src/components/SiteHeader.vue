<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { Separator } from '@/components/ui/separator'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { buildBreadcrumbs } from '@/components/siteBreadcrumbs'
import { useProjectQuery } from '@/composables/queries'

const route = useRoute()

// 只有工作台需要项目名；其它页面传 null，查询保持禁用。
const workbenchProjectId = computed(() =>
  route.name === 'project-workbench' ? String(route.params.id) : null,
)
const { data: project } = useProjectQuery(workbenchProjectId)

const crumbs = computed(() =>
  buildBreadcrumbs({
    routeName: typeof route.name === 'string' ? route.name : undefined,
    title: (route.meta.title as string | undefined) ?? '',
    projectId: workbenchProjectId.value ?? undefined,
    projectTitle: project.value?.title,
    stage: route.params.stage ? String(route.params.stage) : undefined,
  }),
)
</script>

<template>
  <!-- 顶栏不随内容滚动：外壳（App.vue）把滚动限定在它下面的内容区里。 -->
  <header
    class="bg-background flex h-(--header-height) shrink-0 items-center gap-2 border-b transition-[width,height] ease-linear group-has-data-[collapsible=icon]/sidebar-wrapper:h-(--header-height)"
  >
    <div class="flex w-full items-center gap-1 px-4 lg:gap-2 lg:px-6">
      <SidebarTrigger class="-ml-1" />
      <Separator
        orientation="vertical"
        class="mx-2 data-[orientation=vertical]:h-4"
      />
      <Breadcrumb data-testid="site-breadcrumb">
        <BreadcrumbList>
          <template
            v-for="(crumb, index) in crumbs"
            :key="index"
          >
            <BreadcrumbSeparator v-if="index > 0" />
            <BreadcrumbItem>
              <BreadcrumbLink
                v-if="crumb.to"
                :to="crumb.to"
              >
                {{ crumb.label }}
              </BreadcrumbLink>
              <BreadcrumbPage v-else-if="index === crumbs.length - 1">
                {{ crumb.label }}
              </BreadcrumbPage>
              <span v-else>{{ crumb.label }}</span>
            </BreadcrumbItem>
          </template>
        </BreadcrumbList>
      </Breadcrumb>
    </div>
  </header>
</template>
