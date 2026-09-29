<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
const NAV = 'text-black hover:text-blue focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue'
</script>

<template>
  <header>
    <SkipLink />
    <nav class="container-main flex flex-wrap gap-24 py-20 font-mono text-sm" aria-label="Main">
      <NuxtLink to="/" :class="NAV">Conjecture</NuxtLink>
      <NuxtLink to="/engines/" :class="NAV">Engines</NuxtLink>
      <NuxtLink to="/packs/" :class="NAV">Packs</NuxtLink>
      <NuxtLink to="/start/" :class="NAV">Get started</NuxtLink>
      <a href="https://github.com/Opening-Science/conjecture" :class="NAV">Source</a>
    </nav>
  </header>
  <main id="main-content" tabindex="-1">
    <NuxtPage />
  </main>
  <footer class="container-main mt-100 pb-40 font-mono text-sm text-gray">
    Conjecture is the hypothesis hub of the Open Science Foundation (OSF).
    Free software under the AGPL-3.0-or-later.
  </footer>
</template>
