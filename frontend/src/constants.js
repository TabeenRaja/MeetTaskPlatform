export const DEPARTMENTS = [
  "Engineering",
  "Product",
  "Design",
  "Quality Assurance",
  "Operations",
  "Human Resources",
  "Finance",
  "Sales",
  "Marketing",
  "Customer Support",
  "Legal",
  "IT",
];

// value used in the department <select> when the person picks "Other…"
export const OTHER = "__other__";

// Phone numbers: digits only, exactly this many (change here and in serializers.py to adjust)
export const PHONE_LENGTH = 11;
export const cleanPhone = (v) => v.replace(/\D/g, "").slice(0, PHONE_LENGTH);
