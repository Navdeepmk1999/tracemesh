import type { Metadata } from "next";

import { WorkflowList } from "@/components/workflow-list";
import { requireUser } from "@/lib/auth";

export const metadata: Metadata = { title: "Workflows · TraceMesh" };

export default async function WorkflowsPage() {
  await requireUser("/workflows");
  return <WorkflowList />;
}
