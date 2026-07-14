import type { ComponentPropsWithoutRef, ReactNode } from "react";

/**
 * Adapted from Twenty's `Card` and `CardHeader` surfaces in
 * packages/twenty-ui/src/surfaces. The shell keeps the same small, composable
 * surface contract while using the CSUB token names and zero-radius theme.
 */
export function RecordSurface({ children, className = "", ...rest }: ComponentPropsWithoutRef<"section">) {
  return <section className={`panel ${className}`.trim()} {...rest}>{children}</section>;
}

export function RecordSurfaceHeader({ children, className = "", ...rest }: ComponentPropsWithoutRef<"div">) {
  return <div className={`panel-heading ${className}`.trim()} {...rest}>{children}</div>;
}

export function RecordSurfaceContent({ children }: { children: ReactNode }) {
  return <div className="record-surface-content">{children}</div>;
}
