import {
  checkPNRStatus,
  getAvailability,
  searchTrainBetweenStations,
  trackTrain
} from "irctc-connect";

const [, , command, ...args] = process.argv;

function out(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function normalizeJourneyDate(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  const isoMatch = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (isoMatch) {
    return `${isoMatch[3]}-${isoMatch[2]}-${isoMatch[1]}`;
  }
  return text;
}

function formatPnrReply(data) {
  const train = data?.train?.name ? `${data.train.name} (${data.train.number || ""})`.trim() : "Unknown train";
  const journey = data?.journey
    ? `${data.journey.from?.name || data.journey.from?.code || "?"} to ${data.journey.to?.name || data.journey.to?.code || "?"}`
    : "Journey details unavailable";
  const passengers = Array.isArray(data?.passengers) ? data.passengers : [];
  const passengerSummary = passengers.length
    ? passengers
        .map((p, index) => `P${index + 1}: ${p.status || "Unknown"}${p.seat ? ` (${p.seat})` : ""}`)
        .join(", ")
    : "Passenger details unavailable";
  return `PNR ${data?.pnr || ""}: ${data?.status || "Status unavailable"}\nTrain: ${train}\nJourney: ${journey}\nPassengers: ${passengerSummary}`;
}

function formatLiveReply(data) {
  const firstStation = Array.isArray(data?.stations) && data.stations.length ? data.stations[0] : null;
  return `${data?.trainName || "Train"} (${data?.trainNo || ""})\nStatus: ${data?.statusNote || "Live status unavailable"}\nLast update: ${data?.lastUpdate || "Unknown"}${firstStation ? `\nCurrent/first station: ${firstStation.stationName} (${firstStation.stationCode})` : ""}`;
}

function formatAvailabilityReply(data) {
  const availability = Array.isArray(data?.availability) ? data.availability : [];
  const top = availability.slice(0, 3);
  if (!top.length) {
    return "No seat availability details returned for that query.";
  }
  const trainLabel = data?.train?.trainName && data?.train?.trainNo
    ? `${data.train.trainName} (${data.train.trainNo})`
    : "Selected train";
  const routeLabel = data?.train?.fromStationName && data?.train?.toStationName
    ? `${data.train.fromStationName} to ${data.train.toStationName}`
    : "";
  const fareLabel = data?.fare?.totalFare ? `Total fare: Rs ${data.fare.totalFare}` : "";
  const lines = top.map(item => {
    const date = item.date || item.journeyDate || "date";
    const status = item.availabilityText || item.status || item.currentStatus || "Unknown";
    const prediction = item.prediction ? ` (${item.prediction})` : "";
    return `${date}: ${status}${prediction}`;
  });
  return [trainLabel, routeLabel, fareLabel, "Availability", ...lines].filter(Boolean).join("\n");
}

function formatSearchReply(data) {
  const trains = Array.isArray(data) ? data : [];
  return trains.slice(0, 5).map(train => ({
    number: train.train_no || train.trainNo || train.number || "",
    name: train.train_name || train.trainName || train.name || "",
    departure: train.from_time || train.departure || train.fromTime || "",
    arrival: train.to_time || train.arrival || train.toTime || "",
    duration: train.travel_time || train.duration || train.travelTime || "",
    classes: train.classes || train.availableClasses || []
  }));
}

async function main() {
  try {
    if (command === "pnr") {
      const result = await checkPNRStatus(String(args[0] || ""));
      if (!result?.success || result?.data?.success === false) {
        const innerError = result?.data?.error;
        out({ success: false, error: innerError || result?.error || "Failed to fetch PNR status" });
        return;
      }
      if (!result?.data) {
        out({ success: false, error: result?.error || "Failed to fetch PNR status" });
        return;
      }
      out({ success: true, reply: formatPnrReply(result.data) });
      return;
    }

    if (command === "live") {
      const trainNumber = String(args[0] || "");
      const date = normalizeJourneyDate(args[1]) || normalizeJourneyDate(new Date().toISOString().slice(0, 10));
      const result = await trackTrain(trainNumber, date);
      if (!result?.success || !result?.data) {
        out({ success: false, error: result?.error || "Failed to fetch live status" });
        return;
      }
      out({ success: true, reply: formatLiveReply(result.data) });
      return;
    }

    if (command === "availability") {
      const [trainNo, fromCode, toCode, date, coach, quota] = args;
      const result = await getAvailability(
        String(trainNo || ""),
        String(fromCode || ""),
        String(toCode || ""),
        normalizeJourneyDate(date) || "",
        String(coach || "SL"),
        String(quota || "GN")
      );
      if (!result?.success) {
        out({ success: false, error: result?.error || "Failed to fetch availability" });
        return;
      }
      out({ success: true, reply: formatAvailabilityReply(result.data) });
      return;
    }

    if (command === "search") {
      const [fromCode, toCode] = args;
      const result = await searchTrainBetweenStations(String(fromCode || ""), String(toCode || ""));
      if (!result?.success) {
        out({ success: false, error: result?.error || "Failed to search trains" });
        return;
      }
      out({ success: true, trains: formatSearchReply(result.data) });
      return;
    }

    out({ success: false, error: "Unsupported command" });
  } catch (error) {
    out({ success: false, error: error instanceof Error ? error.message : "Unknown error" });
  }
}

await main();
