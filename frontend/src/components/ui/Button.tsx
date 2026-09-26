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
          "inline-flex items-center justify-center font-body font-semibold transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-bg disabled:opacity-50 disabled:pointer-events-none tracking-[0.02em]",
          {
            'bg-accent text-[#FDFAF5] hover:bg-accent-hover shadow-custom-sm active:translate-y-[1px]': variant === 'primary',
            'bg-surface-secondary text-accent hover:bg-[#D4C9B0] active:translate-y-[1px]': variant === 'secondary',
            'bg-[#1A1208] text-[#FDFAF5] hover:bg-[#2C2010] active:translate-y-[1px]': variant === 'inverted',
            'bg-transparent border border-accent text-accent hover:bg-surface-secondary active:translate-y-[1px]': variant === 'outlined',
            'bg-error text-[#FDFAF5] hover:bg-[#7a3232] active:translate-y-[1px]': variant === 'danger',
            'bg-transparent text-fg hover:bg-surface-secondary/60': variant === 'ghost',
            'rounded-[6px] px-[14px] py-[6px] text-[12px]': size === 'sm',
            'rounded-[8px] px-[20px] py-[10px] text-[13px]': size === 'md',
            'rounded-[8px] px-[26px] py-[13px] text-[14px]': size === 'lg',
          },
          className
        )}
        {...props}
      />
    );
  }
);
Button.displayName = 'Button';
