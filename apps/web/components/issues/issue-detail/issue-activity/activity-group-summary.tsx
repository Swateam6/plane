import type { ReactNode } from "react";
import { Collapsible } from "@makeplane/propel/components/collapsible";
import { calculateTimeAgo, renderFormattedDate, renderFormattedTime } from "@plane/utils";

type ActivityGroupSummaryProps = {
  label: string;
  latestCreatedAt: string;
  children: ReactNode;
};

export function ActivityGroupSummary(props: ActivityGroupSummaryProps) {
  const { label, latestCreatedAt, children } = props;

  return (
    <Collapsible
      defaultOpen={false}
      trigger={
        <span className="flex flex-wrap items-center gap-2 text-caption-sm-regular">
          <span className="text-secondary">{label}</span>
          <time
            dateTime={latestCreatedAt}
            title={`${renderFormattedDate(latestCreatedAt)}, ${renderFormattedTime(latestCreatedAt)}`}
            className="text-tertiary"
          >
            {calculateTimeAgo(latestCreatedAt)}
          </time>
        </span>
      }
    >
      <div role="region" aria-label={label} className="pl-3">
        {children}
      </div>
    </Collapsible>
  );
}
