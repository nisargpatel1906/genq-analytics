import React from 'react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'success' | 'warning' | 'error' | 'info' | 'processing' | 'accent';
}

export const Badge = React.forwardRef<HTMLDivElement, BadgeProps>(
  ({ className, variant = 'success', children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          "inline-flex items-center px-2 py-0.5 rounded-[4px] font-body text-[10px] font-semibold uppercase tracking-[0.08em]",
          {
            'bg-[#5C6E3E20] text-[#5C6E3E] border border-[#5C6E3E40]': variant === 'success',
            'bg-[#B8860B20] text-[#B8860B] border border-[#B8860B40]': variant === 'warning',
            'bg-[#8B3A3A20] text-[#8B3A3A] border border-[#8B3A3A40]': variant === 'error',
            'bg-[#755C3B20] text-[#755C3B] border border-[#755C3B40]': variant === 'info',
            'bg-[#8B6F3E20] text-[#8B6F3E] border border-[#8B6F3E40]': variant === 'processing',
            'bg-[#EDE4D0] text-[#8B6F3E] border border-[#D4C9B0]': variant === 'accent',
          },
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }
);
Badge.displayName = 'Badge';
