"use client";

import { Download, MoreVertical, Table2 } from "lucide-react";
import { toast } from "sonner";
import { IconButton, PrimaryButton, SecondaryButton } from "@/components/ramp/buttons";
import { EmptyState } from "@/components/ramp/empty-state";
import { NoticeBanner } from "@/components/ramp/notice-banner";
import { PageHeader } from "@/components/ramp/page-header";
import { SearchToolbar } from "@/components/ramp/search-toolbar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export default function VendorsPage() {
  return (
    <div className="flex min-h-full flex-col px-8 pt-1 pb-10">
      <PageHeader
        title="Vendors"
        actions={
          <>
            <IconButton aria-label="More" onClick={() => toast("More vendor actions aren't part of this prototype.")}>
              <MoreVertical className="size-4" />
            </IconButton>
            <SecondaryButton onClick={() => toast("1099 review isn't part of this prototype.")}>
              Review 1099s
            </SecondaryButton>
            <DropdownMenu>
              <DropdownMenuTrigger
                render={<PrimaryButton chevron>New vendor</PrimaryButton>}
              />
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => toast("Creating a vendor isn't part of this prototype.")}>
                  Create a vendor
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => toast("CSV import isn't part of this prototype.")}>
                  Import from CSV
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        }
      />

      <div className="mt-6">
        <NoticeBanner
          tone="green"
          title="Save time on vendor reviews"
          detail="Auto approve W-9s and tax detail updates from the Vendor Network"
          action="Turn on"
          onAction={() => toast("Vendor Network isn't connected in this prototype.")}
        />
      </div>

      <div className="mt-4 border-b border-[#f0eeea] pb-4">
        <SearchToolbar
          actions={
            <>
              <IconButton aria-label="Columns">
                <Table2 className="size-4" />
              </IconButton>
              <IconButton aria-label="Download">
                <Download className="size-4" />
              </IconButton>
            </>
          }
        />
      </div>

      <div className="flex flex-1 items-center justify-center py-24">
        <EmptyState
          title="No vendors yet"
          subtitle="Add vendors to manage their details and uncover pricing insights"
          action="Import vendors with CSV"
          onAction={() => toast("CSV import isn't part of this prototype.")}
          footnote={
            <>
              Not what you&apos;re looking for? You can also{" "}
              <button
                type="button"
                className="underline decoration-[#c8c4bb] underline-offset-2 hover:decoration-[#1c1c1c]"
                onClick={() => toast("Creating a vendor isn't part of this prototype.")}
              >
                create new vendors manually
              </button>
              .
            </>
          }
        />
      </div>
    </div>
  );
}
