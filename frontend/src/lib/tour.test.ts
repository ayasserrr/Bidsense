import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { hasSeenTour, markTourSeen } from "./tour"

const KEY = "bidsense.tour.seen.v1"

// A small in-memory Storage stand-in, installed fresh for each test. This
// environment's own `window.localStorage` is not reliably usable from a test
// (jsdom/Node's built-in Web Storage here does not expose getItem/setItem
// consistently), so the fake below is what makes these tests deterministic -
// it is also what lets a single test make a call throw on demand, to prove
// hasSeenTour/markTourSeen survive it.
function installFakeStorage(overrides: Partial<Storage> = {}): Storage {
  const store = new Map<string, string>()
  const storage: Storage = {
    getItem: (key: string) => (store.has(key) ? (store.get(key) as string) : null),
    setItem: (key: string, value: string) => {
      store.set(key, value)
    },
    removeItem: (key: string) => {
      store.delete(key)
    },
    clear: () => store.clear(),
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size
    },
    ...overrides,
  }
  Object.defineProperty(window, "localStorage", { value: storage, configurable: true, writable: true })
  return storage
}

// This file is the only one that needs a real, working Storage - restoring
// whatever `window.localStorage` was before each test keeps that swap from
// leaking into any other test file sharing this worker's `window`.
let originalDescriptor: PropertyDescriptor | undefined

beforeEach(() => {
  originalDescriptor = Object.getOwnPropertyDescriptor(window, "localStorage")
  installFakeStorage()
})

afterEach(() => {
  if (originalDescriptor) Object.defineProperty(window, "localStorage", originalDescriptor)
})

describe("tour seen/replay state", () => {
  it("is unseen until marked, then round-trips through localStorage", () => {
    expect(hasSeenTour()).toBe(false)

    markTourSeen()

    expect(hasSeenTour()).toBe(true)
    expect(window.localStorage.getItem(KEY)).toBe("1")
  })

  it("ignores an unrelated stored value", () => {
    window.localStorage.setItem(KEY, "true")
    expect(hasSeenTour()).toBe(false)
  })

  it("survives a localStorage read that throws, reading back as unseen", () => {
    installFakeStorage({
      getItem: () => {
        throw new Error("localStorage blocked")
      },
    })

    expect(() => hasSeenTour()).not.toThrow()
    expect(hasSeenTour()).toBe(false)
  })

  it("survives a localStorage write that throws", () => {
    installFakeStorage({
      setItem: () => {
        throw new Error("localStorage blocked")
      },
    })

    expect(() => markTourSeen()).not.toThrow()
  })
})
