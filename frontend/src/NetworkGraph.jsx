import React, { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';

export default function NetworkGraph({ data, onNodeClick }) {
  const svgRef = useRef(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  useEffect(() => {
    if (!data || !data.nodes || !data.links || !svgRef.current) return;

    // Clear previous graph
    d3.select(svgRef.current).selectAll("*").remove();

    const width = dimensions.width;
    const height = dimensions.height;

    // Create SVG
    const svg = d3.select(svgRef.current)
      .attr("width", width)
      .attr("height", height)
      .attr("viewBox", [0, 0, width, height])
      .attr("style", "max-width: 100%; height: auto;");

    // Create zoom behavior
    const zoom = d3.zoom()
      .scaleExtent([0.5, 5])
      .on("zoom", (event) => {
        g.attr("transform", event.transform);
      });

    svg.call(zoom);

    // Container for zoom
    const g = svg.append("g");

    // Create force simulation
    const simulation = d3.forceSimulation(data.nodes)
      .force("link", d3.forceLink(data.links)
        .id(d => d.id)
        .distance(d => {
          // Stronger links (more weight) = shorter distance
          const weight = d.weight || 1;
          return 100 / Math.sqrt(weight);
        })
      )
      .force("charge", d3.forceManyBody().strength(-300))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(30));

    // Create arrow markers for directed edges
    svg.append("defs").selectAll("marker")
      .data(["coordinated", "normal"])
      .join("marker")
      .attr("id", d => `arrow-${d}`)
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 20)
      .attr("refY", 0)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("fill", d => d === "coordinated" ? "#ef4444" : "#6b7280")
      .attr("d", "M0,-5L10,0L0,5");

    // Create links
    const link = g.append("g")
      .selectAll("line")
      .data(data.links)
      .join("line")
      .attr("stroke", d => {
        // Color by relationship type
        if (d.weight && d.weight > 5) return "#ef4444"; // Red for strong coordination
        if (d.weight && d.weight > 2) return "#f59e0b"; // Orange for moderate
        return "#6b7280"; // Gray for weak
      })
      .attr("stroke-width", d => Math.sqrt(d.weight || 1) * 1.5)
      .attr("stroke-opacity", 0.6)
      .attr("marker-end", d => 
        d.weight && d.weight > 5 ? "url(#arrow-coordinated)" : "url(#arrow-normal)"
      );

    // Add link labels (for interactions)
    const linkLabel = g.append("g")
      .selectAll("text")
      .data(data.links.filter(d => d.weight && d.weight > 2))
      .join("text")
      .attr("font-size", 10)
      .attr("fill", "#9ca3af")
      .attr("text-anchor", "middle")
      .text(d => d.weight);

    // Create nodes
    const node = g.append("g")
      .selectAll("g")
      .data(data.nodes)
      .join("g")
      .call(drag(simulation));

    // Node circles
    node.append("circle")
      .attr("r", d => {
        // Size by influence or degree
        const influence = d.influence || d.degree || 1;
        return 5 + Math.sqrt(influence);
      })
      .attr("fill", d => {
        // Color by community or role
        if (d.community !== undefined) {
          const colors = ["#a855f7", "#3b82f6", "#10b981", "#f59e0b", "#ef4444"];
          return colors[d.community % colors.length];
        }
        // Color by influence level
        const influence = d.influence || 0;
        if (influence > 70) return "#a855f7"; // Purple for high influence
        if (influence > 40) return "#3b82f6"; // Blue for medium
        return "#6b7280"; // Gray for low
      })
      .attr("stroke", "#fff")
      .attr("stroke-width", 2)
      .style("cursor", "pointer");

    // Node labels
    node.append("text")
      .attr("x", 0)
      .attr("y", -15)
      .attr("text-anchor", "middle")
      .attr("font-size", 10)
      .attr("fill", "#e5e7eb")
      .attr("font-weight", "bold")
      .text(d => d.username || d.id);

    // Influence score badge
    node.append("text")
      .attr("x", 0)
      .attr("y", 20)
      .attr("text-anchor", "middle")
      .attr("font-size", 8)
      .attr("fill", "#9ca3af")
      .text(d => d.influence ? `${Math.round(d.influence)}` : "");

    // Add hover effects
    node.on("mouseover", function(event, d) {
      d3.select(this).select("circle")
        .transition()
        .duration(200)
        .attr("stroke-width", 4)
        .attr("stroke", "#a855f7");

      // Highlight connected links
      link.attr("stroke-opacity", l => 
        l.source.id === d.id || l.target.id === d.id ? 1 : 0.2
      );
    })
    .on("mouseout", function() {
      d3.select(this).select("circle")
        .transition()
        .duration(200)
        .attr("stroke-width", 2)
        .attr("stroke", "#fff");

      link.attr("stroke-opacity", 0.6);
    })
    .on("click", function(event, d) {
      setSelectedNode(d);
      if (onNodeClick) onNodeClick(d);
    });

    // Update positions on simulation tick
    simulation.on("tick", () => {
      link
        .attr("x1", d => d.source.x)
        .attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x)
        .attr("y2", d => d.target.y);

      linkLabel
        .attr("x", d => (d.source.x + d.target.x) / 2)
        .attr("y", d => (d.source.y + d.target.y) / 2);

      node.attr("transform", d => `translate(${d.x},${d.y})`);
    });

    // Drag behavior
    function drag(simulation) {
      function dragstarted(event) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        event.subject.fx = event.subject.x;
        event.subject.fy = event.subject.y;
      }

      function dragged(event) {
        event.subject.fx = event.x;
        event.subject.fy = event.y;
      }

      function dragended(event) {
        if (!event.active) simulation.alphaTarget(0);
        event.subject.fx = null;
        event.subject.fy = null;
      }

      return d3.drag()
        .on("start", dragstarted)
        .on("drag", dragged)
        .on("end", dragended);
    }

  }, [data, dimensions]);

  return (
    <div className="relative">
      {/* Graph Container */}
      <div className="bg-black/50 border border-white/10 rounded-lg overflow-hidden">
        <svg ref={svgRef} className="w-full" style={{ minHeight: '600px' }} />
      </div>

      {/* Legend */}
      <div className="mt-4 grid grid-cols-3 gap-4 text-xs">
        <div className="bg-black/50 border border-white/10 rounded-lg p-3">
          <div className="font-semibold mb-2 text-gray-300">Node Size</div>
          <div className="space-y-1 text-gray-400">
            <div>Larger = More influence</div>
            <div>Based on centrality metrics</div>
          </div>
        </div>

        <div className="bg-black/50 border border-white/10 rounded-lg p-3">
          <div className="font-semibold mb-2 text-gray-300">Node Color</div>
          <div className="space-y-1 text-gray-400">
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-purple-500"></div>
              <span>High Influence (&gt;70)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-blue-500"></div>
              <span>Medium Influence (40-70)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-gray-500"></div>
              <span>Low Influence (&lt;40)</span>
            </div>
          </div>
        </div>

        <div className="bg-black/50 border border-white/10 rounded-lg p-3">
          <div className="font-semibold mb-2 text-gray-300">Edge Color</div>
          <div className="space-y-1 text-gray-400">
            <div className="flex items-center gap-2">
              <div className="w-8 h-0.5 bg-red-500"></div>
              <span>Strong coordination</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-8 h-0.5 bg-orange-500"></div>
              <span>Moderate interaction</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-8 h-0.5 bg-gray-500"></div>
              <span>Weak connection</span>
            </div>
          </div>
        </div>
      </div>

      {/* Selected Node Info */}
      {selectedNode && (
        <div className="mt-4 bg-purple-900/20 border border-purple-500/30 rounded-lg p-4">
          <div className="flex justify-between items-start">
            <div>
              <h4 className="font-semibold text-lg">@{selectedNode.username || selectedNode.id}</h4>
              <p className="text-sm text-gray-400">{selectedNode.name || 'Unknown User'}</p>
            </div>
            <button
              onClick={() => setSelectedNode(null)}
              className="text-gray-400 hover:text-white"
            >
              ✕
            </button>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-gray-400">Influence:</span>{' '}
              <span className="text-white font-semibold">{selectedNode.influence || 'N/A'}</span>
            </div>
            <div>
              <span className="text-gray-400">Connections:</span>{' '}
              <span className="text-white font-semibold">{selectedNode.degree || 0}</span>
            </div>
            {selectedNode.betweenness && (
              <div>
                <span className="text-gray-400">Betweenness:</span>{' '}
                <span className="text-white font-semibold">{selectedNode.betweenness.toFixed(2)}</span>
              </div>
            )}
            {selectedNode.eigenvector && (
              <div>
                <span className="text-gray-400">Eigenvector:</span>{' '}
                <span className="text-white font-semibold">{selectedNode.eigenvector.toFixed(2)}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Controls */}
      <div className="mt-4 flex gap-2">
        <button
          onClick={() => {
            const svg = d3.select(svgRef.current);
            svg.transition().duration(750).call(
              d3.zoom().transform,
              d3.zoomIdentity
            );
          }}
          className="px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-sm"
        >
          Reset Zoom
        </button>
        <button
          onClick={() => setDimensions({ width: 1200, height: 800 })}
          className="px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-sm"
        >
          Expand View
        </button>
        <button
          onClick={() => setDimensions({ width: 800, height: 600 })}
          className="px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-sm"
        >
          Default View
        </button>
      </div>
    </div>
  );
}