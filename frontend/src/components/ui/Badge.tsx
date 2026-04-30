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
          "inline-flex items-center px-2 py-0.5 rounded-[4px] font-body text-[10px] font-medium uppercase tracking-[0.1em]",
          {
            'bg-[#5C6E3E20] text-[#5C6E3E] border border-[#5C6E3E40]': variant === 'success',
            'bg-[#B8860B20] text-[#B8860B] border border-[#B8860B40]': variant === 'warning',
            'bg-[#8B3A3A20] text-[#8B3A3A] border border-[#8B3A3A40]': variant === 'error',
            'bg-[#3A5F8B20] text-[#3A5F8B] border border-[#3A5F8B40]': variant === 'info',
            'bg-[#8B6F3E20] text-[#8B6F3E] border border-[#8B6F3E40]': variant === 'processing',
            'bg-accent/15 text-accent border border-accent/30': variant === 'accent',
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
