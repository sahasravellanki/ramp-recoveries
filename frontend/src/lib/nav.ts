import {
  BookOpen,
  Building2,
  CircleDollarSign,
  CreditCard,
  House,
  Landmark,
  List,
  Plane,
  ReceiptText,
  ShoppingBag,
  Sparkles,
  Store,
  type LucideIcon,
} from "lucide-react";

export type NavChild = {
  label: string;
  href: string;
  badge?: string;
};

export type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
  children?: NavChild[];
};

export const MAIN_NAV: NavItem[] = [
  {
    label: "Home",
    href: "/",
    icon: House,
    children: [{ label: "Overview", href: "/" }],
  },
  { label: "Cards and expenses", href: "/cards", icon: CreditCard },
  { label: "Travel", href: "/travel", icon: Plane },
  {
    label: "Bill Pay",
    href: "/bill-pay/bills",
    icon: ReceiptText,
    children: [
      { label: "Bills", href: "/bill-pay/bills" },
      { label: "Recoveries", href: "/bill-pay/recoveries", badge: "New" },
    ],
  },
  { label: "Procurement", href: "/procurement", icon: ShoppingBag },
  { label: "Banking", href: "/banking", icon: Landmark },
  { label: "AI spend", href: "/ai-spend", icon: CircleDollarSign },
];

export const SECONDARY_NAV: NavItem[] = [
  { label: "Accounting", href: "/accounting", icon: BookOpen },
  {
    label: "Vendors",
    href: "/vendors",
    icon: Store,
    children: [
      { label: "Overview", href: "/vendors" },
      { label: "Contracts", href: "/vendors/contracts" },
    ],
  },
  { label: "Policy", href: "/policy", icon: List },
  { label: "Company", href: "/company", icon: Building2 },
];

export const DEMO_USER = {
  firstName: "Sahasra",
  initials: "SC",
  company: "Sunbird Cafe Group",
  email: "ap@sunbirdcafe.example",
};

export function sectionIsActive(item: NavItem, pathname: string) {
  if (item.children?.length) {
    return item.children.some((child) => childIsActive(child, item.children ?? [], pathname));
  }
  return pathMatches(item.href, pathname);
}

export function childIsActive(child: NavChild, siblings: NavChild[], pathname: string) {
  if (pathname === child.href) return true;
  const coveredBySibling = siblings.some(
    (other) =>
      other.href !== child.href &&
      other.href.startsWith(`${child.href}/`) &&
      (pathname === other.href || pathname.startsWith(`${other.href}/`)),
  );
  if (coveredBySibling) return false;
  return pathMatches(child.href, pathname);
}

export function pathMatches(href: string, pathname: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
