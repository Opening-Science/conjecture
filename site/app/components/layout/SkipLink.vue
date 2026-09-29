<script setup lang="ts">
// "Skip to content" link. In the original DOM (reference/dom/home.html) this
// anchor is the FIRST child of the <header> element, so AppHeader renders it
// there — keeping the landmark structure identical to the reference.
</script>

<template>
  <a
    href="#main-content"
    class="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:px-16 focus:py-8"
  >Skip to content</a>
</template>
