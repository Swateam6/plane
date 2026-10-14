import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SidebarMenuItems } from "@/components/workspace/sidebar/sidebar-menu-items";

// Controlled replacement for the application store.
const theme = vi.hoisted(() => ({
  isExtendedSidebarOpened: false,
  toggleExtendedSidebar: vi.fn(),
}));

// Mockup of critical components so ui doesn't need to be generated.
vi.mock("@/hooks/store/use-app-theme", () => ({
  useAppTheme: () => theme,
}));

vi.mock("mobx-react", () => ({
  observer: (component: unknown) => component,
}));

vi.mock("@/hooks/use-local-storage", () => ({
  default: () => ({
    storedValue: true,
    setValue: vi.fn(),
  }),
}));

vi.mock("@/hooks/use-navigation-preferences", () => ({
  usePersonalNavigationPreferences: () => ({
    preferences: { items: {} },
  }),
  useWorkspaceNavigationPreferences: () => ({
    preferences: { items: {} },
  }),
}));

// Remove unrelated navigation items from this focused test.
vi.mock("@plane/constants", () => ({
  WORKSPACE_SIDEBAR_DYNAMIC_NAVIGATION_ITEMS_LINKS: [],
  WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS: {},
  WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS_LINKS: [],
  WORKSPACE_SIDEBAR_STATIC_PINNED_NAVIGATION_ITEMS_LINKS: [],
}));

vi.mock("@makeplane/propel/components/collapsible", () => ({
  Collapsible: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@makeplane/propel/icons", () => ({
  MoreHorizontalOutline: () => null,
}));

vi.mock("@/components/sidebar/sidebar-navigation", () => ({
  SidebarNavItem: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("../components/workspace/sidebar/sidebar-item", () => ({
  SidebarItemBase: () => null,
}));

// Use actual English translations.
// Missing keys return the key itself, matching the reported failure.
vi.mock("@plane/i18n", async () => {
  const { default: accessibility } = await import("../../../packages/i18n/src/locales/en/accessibility.json");

  return {
    useTranslation: () => ({
      t: (key: string) => {
        let value: unknown = accessibility;

        for (const segment of key.split(".")) {
          if (typeof value !== "object" || value === null) {
            return key;
          }

          value = (value as Record<string, unknown>)[segment];
        }

        return typeof value === "string" ? value : key;
      },
    }),
  };
});

beforeEach(() => {
  theme.isExtendedSidebarOpened = false;
  theme.toggleExtendedSidebar.mockReset();
});

afterEach(() => {
  cleanup();
});

// Test cases for issue #10004 - sidebar accessibility.
describe("SidebarMenuItems accessibility — issue #10004", () => {
  it.each([
    { open: false, expected: "Open extended sidebar" },
    { open: true, expected: "Close extended sidebar" },
  ])("uses '$expected' when open=$open", ({ open, expected }) => {
    theme.isExtendedSidebarOpened = open;

    render(<SidebarMenuItems />);

    const button = screen.getByRole("button", {
      name: expected,
    });

    expect(button.getAttribute("aria-label")).toBe(expected);
  });

  it("calls the existing toggle action when clicked", () => {
    render(<SidebarMenuItems />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Open extended sidebar",
      })
    );

    expect(theme.toggleExtendedSidebar).toHaveBeenCalledTimes(1);
  });

  it("updates the accessible name when the state changes", () => {
    const { rerender } = render(<SidebarMenuItems />);

    expect(
      screen.getByRole("button", {
        name: "Open extended sidebar",
      })
    ).toBeTruthy();

    theme.isExtendedSidebarOpened = true;
    rerender(<SidebarMenuItems />);

    expect(
      screen.getByRole("button", {
        name: "Close extended sidebar",
      })
    ).toBeTruthy();
  });
});
