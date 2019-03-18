// APB: 2018. Helper functions for converting CSV data into plats.

  // Take a csv formatted blob of text and convert into a list of dictionaries.
  function getDataPointsFromCSVLines(csv)
  {
    var rawDataPoints = csvLines = points = [];
    csvLines = csv.split(/[\r?\n|\r|\n]+/);

    for (var i = 0; i < csvLines.length; i++)
      if (csvLines[i].length > 0)
      {
        points = csvLines[i].split(",");
        if (points.length < 2)
          continue;
        rawDataPoints.push(
        {
          label: points[0],
          epoch: parseInt(points[1]),
          tuya_current: parseInt(points[2]),
          rachio_zone: parseInt(points[3])
          // indexLabel: points[4]
        });
      }
    return rawDataPoints;
  }


  // Generate a histogram of on-time for Tuya
  function render_new_hist(histPoints, chartName)
  {
    console.log(histPoints);
    var chart = new CanvasJS.Chart(chartName,
    {
      axisY:
      {
        title: "Count",
      },
      title:
      {
        text: "Histogram",
      },
      data: [
      {
        type: "line",
        dataPoints: histPoints
      }]
    });
    chart.render();
  }


  // Plot Tuya and Rachio data
  function render_new_chart(rawDataPoints, chartName, titleText)
  {
    var tuyaPoints = [];
    var rachioPoints = [];
    rawDataPoints.forEach(d => {
                                 tuyaPoints.push({label: d.label, y: d.tuya_current});
                                 rachioPoints.push({label: d.label, y: d.rachio_zone});
                          });

    var chart = new CanvasJS.Chart(chartName,
    {
      animationEnabled: true,
      zoomEnabled: true,
      axisY:{
        // Tuya
        title: "Current",
        lineColor: "#7F6084",
        tickColor: "#7F6084",
        labelFontColor: "#7F6084",
        titleFontColor: "#7F6084",
        suffix: "mA"
      },
      axisY2: {
        // Rachio
        title: "Zone",
        lineColor: "#C24642",
        tickColor: "#C24642",
        labelFontColor: "#C24642",
        titleFontColor: "#C24642",
        minimum: -4,  // -ve numbers are error states
        maximum: 13,  // 12 zones on Rachio
        prefix: "/ ",
        suffix: " /"
      },
      toolTip: {
        shared: true
      },
      legend: {
        cursor: "pointer",
        horizontalAlign: "center",
        verticalAlign: "top",
        fontSize: 10,
        itemclick: toggleDataSeries
      },
      title:
      {
        text: titleText,
      },
      data: [{
        type: "line",
        name: "Current",
        showInLegend: true,
        legendText: "Pump",
        dataPoints: tuyaPoints
      },
      {
        type: "line",
        name: "Zone",
        showInLegend: true,
        legendText: "Rachio Zone",
        axisYType: "secondary",
        dataPoints: rachioPoints
      }]
    });
    console.log(chart);
    chart.render();
  }


// Generic handler to toggle plot
function toggleDataSeries(e) {
    if (typeof (e.dataSeries.visible) === "undefined" || e.dataSeries.visible) {
        e.dataSeries.visible = false;
    } else {
        e.dataSeries.visible = true;
    }
    e.chart.render();
}

