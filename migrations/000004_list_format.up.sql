ALTER TABLE items DROP CONSTRAINT items_format_check;
ALTER TABLE items ADD CONSTRAINT items_format_check CHECK (format IN (
  'text', 'image', 'html', 'chart', 'table', 'log', 'json', 'diff',
  'math', 'media', 'progress', 'list'
));
