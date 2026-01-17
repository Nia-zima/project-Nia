// Minimal Service Worker for PWA recognition
// No offline caching - just registers to satisfy Chrome PWA requirements

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", () => self.clients.claim());
