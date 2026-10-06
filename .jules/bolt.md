## 2024-05-18 - Airtable Search Optimization
**Learning:** In list comprehensions filtering API records (like Airtable fields), calling `.lower()` on a loop invariant (the search keyword) inside the inner `any(...)` loop forces the string transformation for *every field of every record*, creating an O(N*M) penalty.
**Action:** Always pre-compute loop-invariant strings (like `keyword.lower()`) into a local variable before iterating through large record sets.
