"use client";

import ReactMarkdown from "react-markdown";

/**
 * Model output renderer (§B16, §B18): no raw HTML, no images, no auto-loading or external links.
 * External URLs are shown as inert text so they can't exfiltrate data via requests.
 */
export function SafeMarkdown({ children }: { children: string }) {
  return (
    <div className="prose-sm max-w-none space-y-2 text-sm leading-6 [&_li]:ml-5 [&_ol]:list-decimal [&_table]:w-full [&_td]:border [&_td]:border-border [&_td]:px-2 [&_th]:border [&_th]:border-border [&_th]:px-2 [&_ul]:list-disc">
      <ReactMarkdown
        skipHtml
        urlTransform={(url) => (url.startsWith("/") || url.startsWith("#") ? url : "")}
        components={{
          img: ({ alt }) => <span className="text-muted">[image removed{alt ? `: ${alt}` : ""}]</span>,
          a: ({ href, children }) =>
            href ? (
              <a href={href} className="text-accent underline">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
