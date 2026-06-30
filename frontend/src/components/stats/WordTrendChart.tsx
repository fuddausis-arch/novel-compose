export function WordTrendChart() {
  const heights = [40, 60, 30, 80, 55, 90, 70];

  return (
    <div className="flex items-end gap-1 h-20 mt-2">
      {heights.map((height, index) => (
        <div
          key={index}
          className="flex-1 bg-primary rounded-t opacity-70"
          style={{ height: `${height}%` }}
        />
      ))}
    </div>
  );
}
