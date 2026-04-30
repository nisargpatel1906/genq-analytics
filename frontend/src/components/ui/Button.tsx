import React from 'react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'inverted' | 'outlined' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center rounded-[8px] font-body font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-bg disabled:opacity-50 disabled:pointer-events-none tracking-[0.04em]",
          {
            'bg-accent text-[#F5F0E8] hover:bg-accent-hover': variant === 'primary',
            'bg-transparent border border-accent text-accent hover:bg-surface': variant === 'secondary',
            'bg-[#1A1208] text-[#F5F0E8] hover:bg-[#3D2E1A]': variant === 'inverted',
            'bg-transparent border border-border text-fg hover:bg-surface': variant === 'outlined',
            'bg-error text-[#F5F0E8] hover:bg-[#7a3232]': variant === 'danger',
            'bg-transparent text-fg hover:bg-surface': variant === 'ghost',
            'px-[16px] py-[8px] text-[13px]': size === 'sm',
            'px-[20px] py-[10px] text-[13px]': size === 'md',
            'px-[28px] py-[14px] text-[14px]': size === 'lg',
          },
          className
        )}
        {...props}
      />
    );
  }
);
Button.displayName = 'Button';
