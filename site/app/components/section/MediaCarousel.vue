<script setup lang="ts">
// MediaCarousel — an auto-advancing gallery of image / video slides with a
// dotted progress indicator (the active slide is an elongated pill). Slides
// transition horizontally. Video slides autoplay muted only while active and
// hand off to the next slide on 'ended'; image slides advance on a timer.
// Auto-advance pauses on hover/focus and is disabled under reduced motion.
// First use: the /institute Etherlaken hero (owner-directed 2026-07-23).
// design/components/MediaCarousel.md.
//
// A11y (review C17, 2026-08-31): a visible pause/play control (WCAG 2.2.2 —
// hover-pause alone is not a mechanism), inactive slides removed from the
// accessibility tree (aria-hidden + inert), and slide changes announced via a
// polite live region.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

interface Slide {
  type: 'image' | 'video'
  src: string
  alt?: string
}

const props = withDefaults(
  defineProps<{
    slides: Slide[]
    /** Auto-advance interval for image slides (ms); video slides advance on end. */
    intervalMs?: number
    /** Accessible label for the carousel region. */
    label?: string
  }>(),
  { intervalMs: 3500, label: 'Gallery' },
)

const index = ref(0)
const paused = ref(false) // transient: pointer/focus engagement
const userPaused = ref(false) // sticky: the visible pause control
const reduced = ref(false)
const count = computed(() => props.slides.length)

// index -> <video> element (function refs; only video slides register).
const videoEls = new Map<number, HTMLVideoElement>()
function setVideo(el: unknown, i: number): void {
  if (el) videoEls.set(i, el as HTMLVideoElement)
  else videoEls.delete(i)
}

let timer: ReturnType<typeof setTimeout> | undefined
function clearTimer(): void {
  if (timer) {
    clearTimeout(timer)
    timer = undefined
  }
}

function go(i: number): void {
  index.value = (i + count.value) % count.value
}
function next(): void {
  go(index.value + 1)
}
function prev(): void {
  go(index.value - 1)
}

// Touch swipe: a horizontal drag past the threshold changes slide. No
// preventDefault, so vertical page scrolling still works.
const SWIPE_THRESHOLD = 40
let touchStartX: number | null = null
function onTouchStart(e: TouchEvent): void {
  touchStartX = e.changedTouches[0]?.screenX ?? null
  pause()
}
function onTouchEnd(e: TouchEvent): void {
  if (touchStartX !== null) {
    const dx = (e.changedTouches[0]?.screenX ?? touchStartX) - touchStartX
    if (dx <= -SWIPE_THRESHOLD) next()
    else if (dx >= SWIPE_THRESHOLD) prev()
  }
  touchStartX = null
  resume()
}

// Play the active slide's video from the start. Independent of `paused`
// (pausing halts AUTO-ADVANCE, not the content the user navigated to);
// gated only by reduced motion.
function playActiveVideo(): void {
  if (reduced.value || userPaused.value) return
  if (props.slides[index.value]?.type !== 'video') return
  const v = videoEls.get(index.value)
  if (!v) return
  v.muted = true
  v.currentTime = 0
  void v.play().catch(() => {})
}

function schedule(): void {
  clearTimer()
  if (reduced.value || paused.value || userPaused.value) return
  // Video slides advance on their 'ended' event, not the timer.
  if (props.slides[index.value]?.type === 'video') return
  timer = setTimeout(next, props.intervalMs)
}

watch(index, () => {
  videoEls.forEach((v) => v.pause())
  playActiveVideo()
  schedule()
})

// A video finishing advances the gallery — unless the user is engaged (paused).
function onEnded(): void {
  if (!paused.value && !userPaused.value && !reduced.value) next()
}

// The visible pause/play control: pausing stops BOTH auto-advance and the
// active video (WCAG 2.2.2 pauses the moving content, not just the rotation).
function togglePlayback(): void {
  userPaused.value = !userPaused.value
  if (userPaused.value) {
    clearTimer()
    videoEls.get(index.value)?.pause()
  } else {
    // Resume, don't restart: playActiveVideo() rewinds to 0 (slide-change
    // semantics). A finished video does restart; a mid-video pause resumes.
    const v = videoEls.get(index.value)
    if (v && props.slides[index.value]?.type === 'video' && !reduced.value) {
      if (v.ended) playActiveVideo()
      else void v.play().catch(() => {})
    }
    schedule()
  }
}

// Pause/resume affect AUTO-ADVANCE only; a playing video keeps playing.
function pause(): void {
  paused.value = true
  clearTimer()
}
function resume(): void {
  paused.value = false
  const v = videoEls.get(index.value)
  // Video finished while engaged — move on now, but never past an explicit
  // user pause (the visible control's guarantee outranks hover state).
  if (v && v.ended && !userPaused.value) next()
  else schedule()
}

onMounted(() => {
  reduced.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  playActiveVideo()
  schedule()
})
onBeforeUnmount(clearTimer)

const trackStyle = computed(() => ({ transform: `translateX(-${index.value * 100}%)` }))
</script>

<template>
  <div
    class="w-full"
    role="group"
    aria-roledescription="carousel"
    :aria-label="label"
    @mouseenter="pause"
    @mouseleave="resume"
    @focusin="pause"
    @focusout="resume"
    @keydown.left.prevent="prev"
    @keydown.right.prevent="next"
  >
    <div
      class="relative aspect-video w-full overflow-hidden rounded-xl bg-cream"
      @touchstart="onTouchStart"
      @touchend="onTouchEnd"
    >
      <div
        class="flex h-full"
        :class="reduced ? '' : 'transition-transform duration-300 ease-out'"
        :style="trackStyle"
      >
        <div
          v-for="(s, i) in slides"
          :key="i"
          class="h-full w-full shrink-0"
          :aria-hidden="i !== index ? 'true' : undefined"
          :inert="i !== index"
        >
          <video
            v-if="s.type === 'video'"
            :ref="(el) => setVideo(el, i)"
            :src="s.src"
            muted
            playsinline="true"
            preload="metadata"
            class="h-full w-full object-cover"
            @ended="onEnded"
            @error="onEnded"
          ></video>
          <img v-else :src="s.src" :alt="s.alt ?? ''" class="h-full w-full object-cover">
        </div>
      </div>
    </div>

    <!-- polite announcement of the visible slide for screen readers -->
    <div class="sr-only" aria-live="polite">Slide {{ index + 1 }} of {{ count }}<template v-if="slides[index]?.alt">: {{ slides[index]?.alt }}</template></div>

    <!-- dotted progress bar: one dot per slide, active = elongated pill,
         plus the visible pause/play control (WCAG 2.2.2) -->
    <div class="mt-16 flex items-center justify-center gap-8">
      <button
        v-for="(s, i) in slides"
        :key="i"
        type="button"
        :aria-label="`Show slide ${i + 1} of ${count}`"
        :aria-current="i === index ? 'true' : undefined"
        class="h-8 rounded-full transition-all duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue"
        :class="i === index ? 'w-24 bg-black' : 'w-8 bg-cream-dark hover:bg-cream-darker'"
        @click="go(i)"
      />
      <button
        type="button"
        class="ml-8 cursor-pointer font-mono text-sm text-gray transition-colors hover:text-black focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue"
        :aria-label="userPaused ? 'Play the gallery' : 'Pause the gallery'"
        @click="togglePlayback"
      >{{ userPaused ? 'Play' : 'Pause' }}</button>
    </div>
  </div>
</template>
